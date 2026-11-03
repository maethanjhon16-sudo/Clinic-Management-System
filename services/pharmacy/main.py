import logging
import os
import time
import uuid
from datetime import date, datetime, timezone
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from db import Base, SessionLocal, get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pharmacy")

STUDENT_SERVICE_URL = os.environ.get("STUDENT_SERVICE_URL", "").rstrip("/")
NOTIFICATION_SERVICE_URL = os.environ.get("NOTIFICATION_SERVICE_URL", "").rstrip("/")  # optional
MAX_OPEN_INQUIRIES = int(os.environ.get("MAX_OPEN_INQUIRIES", "3"))
EXCUSE_SERVICE_URL = os.environ.get("EXCUSE_SERVICE_URL", "").rstrip("/")
TZ = ZoneInfo(os.environ.get("CLINIC_TIMEZONE", "Asia/Manila"))

# Free hosts sleep idle services (about 1 minute to wake), so allow long waits and retry.
http = httpx.Client(timeout=httpx.Timeout(90.0, connect=90.0))
MAX_ATTEMPTS = 4

app = FastAPI(title="Pharmacy Service", version="2.0.0")


# ---------- errors ----------
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details


def body(code: str, message: str, details=None) -> dict:
    return {"code": code, "message": message, "details": details}


@app.exception_handler(ApiError)
async def api_error(_: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content=body(exc.code, exc.message, exc.details))


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    code = {404: "NOT_FOUND", 409: "CONFLICT"}.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(status_code=exc.status_code, content=body(code, str(exc.detail)))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "issue": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content=body("VALIDATION_ERROR", "Invalid request data", details))


# ---------- models ----------
class Medicine(Base):
    __tablename__ = "medicines"
    __table_args__ = {"schema": "pharmacy"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    reorder_level: Mapped[int] = mapped_column(Integer, default=10)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    treats: Mapped[str | None] = mapped_column(String, nullable=True)


class DispensingRecord(Base):
    __tablename__ = "dispensing_records"
    __table_args__ = {"schema": "pharmacy"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prescription_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    consultation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    medicine_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pharmacy.medicines.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="reserved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- schemas ----------
class MedicineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    unit: str | None = Field(default=None, max_length=30)
    stock: int = Field(default=0, ge=0, le=1_000_000)
    reorder_level: int = Field(default=10, ge=0, le=1_000_000)
    expiry_date: date | None = None
    treats: str | None = Field(default=None, max_length=200)


class MedicineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    unit: str | None = Field(default=None, max_length=30)
    reorder_level: int | None = Field(default=None, ge=0, le=1_000_000)
    expiry_date: date | None = None
    treats: str | None = Field(default=None, max_length=200)


class Restock(BaseModel):
    quantity: int = Field(gt=0, le=100_000)


class MedicineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    unit: str | None
    stock: int
    reorder_level: int
    expiry_date: date | None
    treats: str | None = None
    low_stock: bool = False
    expired: bool = False


class DispenseItem(BaseModel):
    prescription_id: uuid.UUID
    medicine_id: uuid.UUID
    quantity: int = Field(gt=0, le=1000)


class DispenseRequest(BaseModel):
    consultation_id: uuid.UUID
    student_id: uuid.UUID
    items: list[DispenseItem] = Field(min_length=1, max_length=20)


class DispensingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    prescription_id: uuid.UUID
    consultation_id: uuid.UUID | None
    student_id: uuid.UUID | None
    medicine_id: uuid.UUID
    quantity: int
    status: str
    created_at: datetime
    updated_at: datetime


# ---------- helpers ----------
def today() -> date:
    return datetime.now(timezone.utc).date()


def now() -> datetime:
    return datetime.now(timezone.utc)


def med_out(m: Medicine) -> MedicineOut:
    out = MedicineOut.model_validate(m)
    out.low_stock = m.stock <= m.reorder_level
    out.expired = bool(m.expiry_date and m.expiry_date < today())
    return out


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        text = str(exc.orig)
        if "uq_active_prescription" in text:
            raise ApiError(409, "DUPLICATE_DISPENSE", "This prescription was just dispensed by another request")
        if "name" in text:
            raise ApiError(409, "CONFLICT", "A medicine with this name already exists")
        raise ApiError(409, "CONFLICT", "The change conflicts with existing data")


def locked_medicine(db: Session, medicine_id: uuid.UUID) -> Medicine:
    medicine = db.execute(select(Medicine).where(Medicine.id == medicine_id).with_for_update()).scalar_one_or_none()
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")
    return medicine


def get_record(db: Session, record_id: uuid.UUID) -> DispensingRecord:
    record = db.get(DispensingRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Dispensing record not found")
    return record


# ---------- health ----------
@app.get("/health")
def health():
    return {"status": "ok", "service": "pharmacy"}


# ---------- medicines ----------
@app.post("/medicines", response_model=MedicineOut, status_code=201)
def create_medicine(payload: MedicineCreate, db: Session = Depends(get_db)):
    medicine = Medicine(**payload.model_dump())
    db.add(medicine)
    commit_or_conflict(db)
    db.refresh(medicine)
    return med_out(medicine)


@app.get("/medicines", response_model=list[MedicineOut])
def list_medicines(
    q: str | None = Query(default=None, description="Search by name"),
    low_stock_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Medicine)
    if q:
        stmt = stmt.where(Medicine.name.ilike(f"%{q}%"))
    if low_stock_only:
        stmt = stmt.where(Medicine.stock <= Medicine.reorder_level)
    rows = db.scalars(stmt.order_by(Medicine.name).limit(limit).offset(offset)).all()
    return [med_out(m) for m in rows]


@app.get("/medicines/{medicine_id}", response_model=MedicineOut)
def get_medicine(medicine_id: uuid.UUID, db: Session = Depends(get_db)):
    medicine = db.get(Medicine, medicine_id)
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")
    return med_out(medicine)


@app.put("/medicines/{medicine_id}", response_model=MedicineOut)
def update_medicine(medicine_id: uuid.UUID, payload: MedicineUpdate, db: Session = Depends(get_db)):
    medicine = locked_medicine(db, medicine_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(medicine, field, value)
    commit_or_conflict(db)
    db.refresh(medicine)
    return med_out(medicine)


@app.post("/medicines/{medicine_id}/restock", response_model=MedicineOut)
def restock_medicine(medicine_id: uuid.UUID, payload: Restock, db: Session = Depends(get_db)):
    medicine = locked_medicine(db, medicine_id)
    medicine.stock += payload.quantity
    db.commit()
    db.refresh(medicine)
    log.info("restocked %s by %d -> %d", medicine.name, payload.quantity, medicine.stock)
    return med_out(medicine)


# ---------- dispensing ----------
@app.post("/dispense", response_model=list[DispensingOut], status_code=201)
def dispense(payload: DispenseRequest, response: Response, db: Session = Depends(get_db)):
    """Called by the Consultation service. All-or-nothing, and safe to repeat for the same prescriptions."""
    prescription_ids = [i.prescription_id for i in payload.items]
    existing = db.scalars(
        select(DispensingRecord).where(DispensingRecord.prescription_id.in_(prescription_ids),
                                       DispensingRecord.status != "cancelled")
    ).all()
    done = {r.prescription_id for r in existing}
    new_items = [i for i in payload.items if i.prescription_id not in done]
    if not new_items:  # a retry: nothing left to do, nothing deducted twice
        response.status_code = 200
        return existing

    needed: dict[uuid.UUID, int] = {}
    for item in new_items:
        needed[item.medicine_id] = needed.get(item.medicine_id, 0) + item.quantity

    # Lock the rows (in a fixed order) so two requests cannot sell the same stock twice.
    medicines = db.scalars(select(Medicine).where(Medicine.id.in_(list(needed))).order_by(Medicine.id).with_for_update()).all()
    by_id = {m.id: m for m in medicines}

    problems = []
    for medicine_id, quantity in needed.items():
        medicine = by_id.get(medicine_id)
        if not medicine:
            problems.append({"code": "INVALID_MEDICINE", "medicine_id": str(medicine_id), "issue": "medicine does not exist"})
        elif medicine.expiry_date and medicine.expiry_date < today():
            problems.append({"code": "MEDICINE_EXPIRED", "medicine_id": str(medicine_id), "name": medicine.name,
                             "issue": f"expired on {medicine.expiry_date.isoformat()}"})
        elif medicine.stock < quantity:
            problems.append({"code": "INSUFFICIENT_STOCK", "medicine_id": str(medicine_id), "name": medicine.name,
                             "issue": f"requested {quantity}, only {medicine.stock} in stock"})
    if problems:
        db.rollback()
        codes = {p["code"] for p in problems}
        code = codes.pop() if len(codes) == 1 else "DISPENSE_REJECTED"
        raise ApiError(422, code, "The prescription cannot be dispensed", problems)

    records = []
    for medicine_id, quantity in needed.items():
        by_id[medicine_id].stock -= quantity
    for item in new_items:
        record = DispensingRecord(prescription_id=item.prescription_id, consultation_id=payload.consultation_id,
                                  student_id=payload.student_id, medicine_id=item.medicine_id,
                                  quantity=item.quantity, status="reserved")
        db.add(record)
        records.append(record)
    commit_or_conflict(db)
    for record in records:
        db.refresh(record)
    log.info("reserved %d item(s) for consultation %s", len(records), payload.consultation_id)
    return existing + records


@app.get("/dispensing", response_model=list[DispensingOut])
def list_dispensing(
    consultation_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(reserved|dispensed|cancelled|failed)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(DispensingRecord)
    if consultation_id:
        stmt = stmt.where(DispensingRecord.consultation_id == consultation_id)
    if student_id:
        stmt = stmt.where(DispensingRecord.student_id == student_id)
    if status:
        stmt = stmt.where(DispensingRecord.status == status)
    return db.scalars(stmt.order_by(DispensingRecord.created_at.desc()).limit(limit).offset(offset)).all()


@app.get("/dispensing/{record_id}", response_model=DispensingOut)
def read_dispensing(record_id: uuid.UUID, db: Session = Depends(get_db)):
    return get_record(db, record_id)


@app.patch("/dispensing/{record_id}/confirm", response_model=DispensingOut)
def confirm_dispensing(record_id: uuid.UUID, db: Session = Depends(get_db)):
    """The pharmacist hands the medicine to the student."""
    record = get_record(db, record_id)
    if record.status != "reserved":
        raise ApiError(409, "INVALID_STATE", f"A {record.status} record cannot be confirmed")
    record.status = "dispensed"
    record.updated_at = now()
    db.commit()
    db.refresh(record)
    return record


@app.patch("/dispensing/{record_id}/cancel", response_model=DispensingOut)
def cancel_dispensing(record_id: uuid.UUID, db: Session = Depends(get_db)):
    """Release a reservation and put the stock back."""
    record = get_record(db, record_id)
    if record.status != "reserved":
        raise ApiError(409, "INVALID_STATE", f"A {record.status} record cannot be cancelled")
    medicine = locked_medicine(db, record.medicine_id)
    medicine.stock += record.quantity
    record.status = "cancelled"
    record.updated_at = now()
    db.commit()
    db.refresh(record)
    return record


# =====================================================================
# Medicine inquiries: a student asks, the nurse checks stock and answers
# =====================================================================
class MedicineInquiry(Base):
    __tablename__ = "medicine_inquiries"
    __table_args__ = {"schema": "pharmacy"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    symptoms: Mapped[str] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    medicine_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pharmacy.medicines.id"), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pickup_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    response_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    handled_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    handled_by_name: Mapped[str | None] = mapped_column(String, nullable=True)
    fit_for_class: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rest_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excuse_slip_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    excuse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InquiryCreate(BaseModel):
    student_id: uuid.UUID | None = None     # only used when staff log an inquiry for a student
    symptoms: list[str] = Field(min_length=1, max_length=8)
    details: str | None = Field(default=None, max_length=500)

    @field_validator("symptoms")
    @classmethod
    def clean_symptoms(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            item = value.strip().lower()
            if not item or len(item) > 40:
                raise ValueError("each symptom must be 1 to 40 characters")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned


class RespondIn(BaseModel):
    available: bool
    medicine_id: uuid.UUID | None = None
    quantity: int | None = Field(default=None, gt=0, le=1000)
    pickup_date: date | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def available_needs_details(self):
        if self.available and not (self.medicine_id and self.quantity and self.pickup_date):
            raise ValueError("medicine, quantity and pick-up date are required when the medicine is available")
        return self


class CollectIn(BaseModel):
    fit_for_class: bool = True               # the nurse's check in person when the student comes for the medicine
    rest_days: int | None = Field(default=None, ge=1, le=30)

    @model_validator(mode="after")
    def rest_days_needed(self):
        if not self.fit_for_class and self.rest_days is None:
            raise ValueError("rest_days is required when the student is not fit to continue classes")
        return self


class SuggestionOut(BaseModel):
    medicine_id: uuid.UUID
    name: str
    unit: str | None
    stock: int


class InquiryOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    symptoms: list[str]
    details: str | None
    status: str
    medicine_id: uuid.UUID | None
    medicine_name: str | None
    quantity: int | None
    pickup_date: date | None
    response_note: str | None
    handled_by_name: str | None
    fit_for_class: bool | None = None
    rest_days: int | None = None
    excuse_slip_id: uuid.UUID | None = None
    excuse_error: str | None = None
    created_at: datetime
    updated_at: datetime
    suggestions: list[SuggestionOut] = []


class Actor:
    def __init__(self, role, student_id, user_id, name):
        self.role, self.student_id, self.user_id, self.name = role, student_id, user_id, name


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def actor_of(request: Request) -> Actor:
    """Who is calling. These headers are set by the gateway after it has checked the login."""
    raw_name = request.headers.get("x-user-name")
    return Actor(request.headers.get("x-user-role"), _uuid_or_none(request.headers.get("x-student-id")),
                 _uuid_or_none(request.headers.get("x-user-id")), unquote(raw_name) if raw_name else None)


def request_id_of(request: Request) -> str:
    return request.headers.get("x-request-id", str(uuid.uuid4()))


def clinic_today() -> date:
    return datetime.now(TZ).date()


def tags(text: str | None) -> set[str]:
    return {t.strip().lower() for t in (text or "").split(",") if t.strip()}


def suggestions_for(inquiry: MedicineInquiry, medicines: list[Medicine]) -> list[SuggestionOut]:
    wanted = tags(inquiry.symptoms)
    return [SuggestionOut(medicine_id=m.id, name=m.name, unit=m.unit, stock=m.stock)
            for m in medicines
            if m.stock > 0 and not (m.expiry_date and m.expiry_date < today()) and wanted & tags(m.treats)]


def inquiry_out(inquiry: MedicineInquiry, medicines: list[Medicine], show_suggestions: bool) -> InquiryOut:
    medicine = next((m for m in medicines if m.id == inquiry.medicine_id), None)
    return InquiryOut(
        id=inquiry.id, student_id=inquiry.student_id, symptoms=[s.strip() for s in inquiry.symptoms.split(",") if s.strip()],
        details=inquiry.details, status=inquiry.status, medicine_id=inquiry.medicine_id,
        medicine_name=medicine.name if medicine else None, quantity=inquiry.quantity, pickup_date=inquiry.pickup_date,
        response_note=inquiry.response_note, handled_by_name=inquiry.handled_by_name,
        fit_for_class=inquiry.fit_for_class, rest_days=inquiry.rest_days,
        excuse_slip_id=inquiry.excuse_slip_id, excuse_error=inquiry.excuse_error,
        created_at=inquiry.created_at, updated_at=inquiry.updated_at,
        suggestions=suggestions_for(inquiry, medicines) if show_suggestions and inquiry.status == "pending" else [],
    )


def all_medicines(db: Session) -> list[Medicine]:
    return list(db.scalars(select(Medicine)).all())


def call(method: str, url: str, request_id: str, json=None) -> httpx.Response:
    """HTTP call with retries while a sleeping service wakes up (POST only when surely not processed)."""
    is_get = method == "GET"
    retry_statuses = {502, 503, 504} if is_get else {502, 503}
    retry_exceptions = (httpx.ConnectError, httpx.ConnectTimeout) + ((httpx.ReadTimeout,) if is_get else ())
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = http.request(method, url, json=json,
                                    headers={"x-request-id": request_id, "accept-encoding": "identity"})
        except retry_exceptions as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            log.warning("%s %s failed (%s), attempt %d/%d", request_id, url, type(exc).__name__, attempt, MAX_ATTEMPTS)
            time.sleep(2 ** attempt)
            continue
        if response.status_code in retry_statuses and attempt < MAX_ATTEMPTS:
            time.sleep(6 * attempt)
            continue
        return response


def check_student(student_id: uuid.UUID, request_id: str) -> dict:
    """Integration point: the student must exist and be active."""
    if not STUDENT_SERVICE_URL:
        raise ApiError(503, "SERVICE_NOT_CONFIGURED", "STUDENT_SERVICE_URL is not configured")
    try:
        response = call("GET", f"{STUDENT_SERVICE_URL}/students/{student_id}", request_id)
    except httpx.HTTPError as exc:
        raise ApiError(503, "STUDENT_SERVICE_UNAVAILABLE", "The student service is not responding",
                       {"request_id": request_id, "reason": type(exc).__name__})
    if response.status_code == 404:
        raise ApiError(422, "INVALID_STUDENT", "The student does not exist")
    if response.status_code != 200:
        raise ApiError(502, "STUDENT_SERVICE_ERROR", f"The student service returned status {response.status_code}")
    student = response.json()
    if not student.get("is_active", False):
        raise ApiError(422, "STUDENT_INACTIVE", "The student record is inactive")
    return student


def notify_inquiry(inquiry_id: uuid.UUID, request_id: str) -> None:
    """Background task: email the student the nurse's answer. A failure never undoes the answer."""
    if not (NOTIFICATION_SERVICE_URL and STUDENT_SERVICE_URL):
        return
    try:
        with SessionLocal() as db:
            inquiry = db.get(MedicineInquiry, inquiry_id)
            if not inquiry:
                return
            medicine = db.get(Medicine, inquiry.medicine_id) if inquiry.medicine_id else None
            found = call("GET", f"{STUDENT_SERVICE_URL}/students/{inquiry.student_id}", request_id)
            if found.status_code != 200:
                return
            student = found.json()
            symptoms = inquiry.symptoms
            note = f"\n\nNote from the nurse: {inquiry.response_note}" if inquiry.response_note else ""
            if inquiry.status == "ready" and inquiry.pickup_date:
                kind, subject = "inquiry_ready", "Your medicine is available"
                what = f"{medicine.name} x{inquiry.quantity}" if medicine else "the medicine"
                message = (f"The clinic has {what} available for your inquiry about {symptoms}. "
                           f"You may pick it up on {inquiry.pickup_date.strftime('%B %d, %Y')}.{note}")
            else:
                kind, subject = "inquiry_unavailable", "Update on your medicine inquiry"
                message = f"The clinic does not have a medicine available right now for your inquiry about {symptoms}.{note}"
            call("POST", f"{NOTIFICATION_SERVICE_URL}/notifications", request_id,
                 json={"recipient_email": student["email"], "type": kind, "subject": subject,
                       "body": f"Hello {student['full_name']},\n\n{message}\n\nSchool Clinic",
                       "related_id": str(inquiry.id)})
    except Exception as exc:
        log.warning("%s could not send the inquiry notification: %s", request_id, exc)


def locked_inquiry(db: Session, inquiry_id: uuid.UUID) -> MedicineInquiry:
    inquiry = db.execute(select(MedicineInquiry).where(MedicineInquiry.id == inquiry_id).with_for_update()).scalar_one_or_none()
    if not inquiry:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    return inquiry


def ensure_inquiry_access(inquiry: MedicineInquiry, actor: Actor) -> None:
    if actor.role == "student" and (actor.student_id is None or actor.student_id != inquiry.student_id):
        raise ApiError(403, "FORBIDDEN", "Students can only manage their own inquiries")


@app.post("/inquiries", response_model=InquiryOut, status_code=201)
def create_inquiry(payload: InquiryCreate, request: Request, db: Session = Depends(get_db)):
    actor = actor_of(request)
    if actor.role == "student":
        if actor.student_id is None:
            raise ApiError(403, "FORBIDDEN", "This account is not linked to a student record")
        student_id = actor.student_id
    else:
        if payload.student_id is None:
            raise ApiError(422, "STUDENT_REQUIRED", "Please select the student for this inquiry")
        student_id = payload.student_id
    check_student(student_id, request_id_of(request))
    open_count = db.scalar(select(func.count()).select_from(MedicineInquiry).where(
        MedicineInquiry.student_id == student_id, MedicineInquiry.status.in_(["pending", "ready"]))) or 0
    if open_count >= MAX_OPEN_INQUIRIES:
        raise ApiError(409, "LIMIT_REACHED", f"You can have at most {MAX_OPEN_INQUIRIES} open inquiries at a time")
    inquiry = MedicineInquiry(student_id=student_id, symptoms=", ".join(payload.symptoms), details=payload.details)
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    return inquiry_out(inquiry, [], False)


@app.get("/inquiries", response_model=list[InquiryOut])
def list_inquiries(
    request: Request,
    student_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(pending|ready|unavailable|collected|cancelled)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    actor = actor_of(request)
    if actor.role == "student":
        if actor.student_id is None:
            raise ApiError(403, "FORBIDDEN", "This account is not linked to a student record")
        student_id = actor.student_id
    stmt = select(MedicineInquiry)
    if student_id:
        stmt = stmt.where(MedicineInquiry.student_id == student_id)
    if status:
        stmt = stmt.where(MedicineInquiry.status == status)
    rows = db.scalars(stmt.order_by(MedicineInquiry.created_at.desc()).limit(limit).offset(offset)).all()
    medicines = all_medicines(db)
    return [inquiry_out(r, medicines, actor.role != "student") for r in rows]


@app.get("/inquiries/{inquiry_id}", response_model=InquiryOut)
def read_inquiry(inquiry_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    actor = actor_of(request)
    inquiry = db.get(MedicineInquiry, inquiry_id)
    if not inquiry:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    ensure_inquiry_access(inquiry, actor)
    return inquiry_out(inquiry, all_medicines(db), actor.role != "student")


@app.post("/inquiries/{inquiry_id}/respond", response_model=InquiryOut)
def respond_to_inquiry(inquiry_id: uuid.UUID, payload: RespondIn, request: Request,
                       background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """The nurse checks the stock. If the medicine is available, the stock is set aside until pick-up."""
    actor = actor_of(request)
    if actor.role == "student":
        raise ApiError(403, "FORBIDDEN", "Only clinic staff can respond to inquiries")
    inquiry = locked_inquiry(db, inquiry_id)
    if inquiry.status != "pending":
        raise ApiError(409, "INVALID_STATE", f"A {inquiry.status} inquiry cannot be answered again")
    if payload.available:
        if payload.pickup_date < clinic_today():
            raise ApiError(422, "PAST_DATE", "The pick-up date cannot be in the past")
        medicine = locked_medicine(db, payload.medicine_id)
        if medicine.expiry_date and medicine.expiry_date < today():
            raise ApiError(422, "MEDICINE_EXPIRED", f"{medicine.name} has expired")
        if medicine.stock < payload.quantity:
            raise ApiError(422, "INSUFFICIENT_STOCK", f"Only {medicine.stock} of {medicine.name} in stock")
        medicine.stock -= payload.quantity
        inquiry.status, inquiry.medicine_id = "ready", medicine.id
        inquiry.quantity, inquiry.pickup_date = payload.quantity, payload.pickup_date
    else:
        inquiry.status = "unavailable"
    inquiry.response_note = payload.note
    inquiry.handled_by_id, inquiry.handled_by_name, inquiry.updated_at = actor.user_id, actor.name, now()
    db.commit()
    db.refresh(inquiry)
    background_tasks.add_task(notify_inquiry, inquiry.id, request_id_of(request))
    return inquiry_out(inquiry, all_medicines(db), True)


def issue_excuse_task(inquiry_id: uuid.UUID, request_id: str) -> None:
    """Background task: ask the Excuse service for a slip. Repeating it is safe (one slip per inquiry)."""
    with SessionLocal() as db:
        inquiry = db.get(MedicineInquiry, inquiry_id)
        if not inquiry or inquiry.fit_for_class is not False or inquiry.excuse_slip_id:
            return
        try:
            if not EXCUSE_SERVICE_URL:
                raise RuntimeError("EXCUSE_SERVICE_URL is not configured")
            response = call("POST", f"{EXCUSE_SERVICE_URL}/excuses", request_id,
                            json={"inquiry_id": str(inquiry.id), "student_id": str(inquiry.student_id),
                                  "rest_days": inquiry.rest_days, "issued_on": clinic_today().isoformat()})
            if 200 <= response.status_code < 300:
                inquiry.excuse_slip_id = uuid.UUID(response.json()["id"])
                inquiry.excuse_error = None
            else:
                inquiry.excuse_error = f"The excuse service answered with status {response.status_code}"
        except Exception as exc:
            log.warning("%s could not issue the excuse slip: %s", request_id, exc)
            inquiry.excuse_error = f"The excuse service could not be reached ({type(exc).__name__})"
        inquiry.updated_at = now()
        db.commit()


@app.post("/inquiries/{inquiry_id}/collect", response_model=InquiryOut)
def collect_inquiry(inquiry_id: uuid.UUID, payload: CollectIn, request: Request,
                    background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """The student picked up the medicine. The nurse records whether the student can continue classes;
    if not, an excuse slip is issued (in the background, so a sleeping service never blocks the nurse)."""
    actor = actor_of(request)
    if actor.role == "student":
        raise ApiError(403, "FORBIDDEN", "Only clinic staff can do this")
    inquiry = locked_inquiry(db, inquiry_id)
    if inquiry.status != "ready":
        raise ApiError(409, "INVALID_STATE", f"A {inquiry.status} inquiry cannot be marked as collected")
    inquiry.status, inquiry.updated_at = "collected", now()
    inquiry.fit_for_class = payload.fit_for_class
    inquiry.rest_days = None if payload.fit_for_class else payload.rest_days
    inquiry.excuse_error = None
    db.commit()
    db.refresh(inquiry)
    if not payload.fit_for_class:
        background_tasks.add_task(issue_excuse_task, inquiry.id, request_id_of(request))
    return inquiry_out(inquiry, all_medicines(db), True)


@app.post("/inquiries/{inquiry_id}/issue-excuse", response_model=InquiryOut)
def retry_issue_excuse(inquiry_id: uuid.UUID, request: Request, background_tasks: BackgroundTasks,
                       db: Session = Depends(get_db)):
    """Try again to issue the excuse slip when it could not be created the first time."""
    if actor_of(request).role == "student":
        raise ApiError(403, "FORBIDDEN", "Only clinic staff can do this")
    inquiry = locked_inquiry(db, inquiry_id)
    if inquiry.status != "collected" or inquiry.fit_for_class is not False:
        raise ApiError(409, "INVALID_STATE", "There is no pending excuse slip for this inquiry")
    if inquiry.excuse_slip_id:
        raise ApiError(409, "ALREADY_ISSUED", "The excuse slip was already issued")
    inquiry.excuse_error = None
    inquiry.updated_at = now()
    db.commit()
    db.refresh(inquiry)
    background_tasks.add_task(issue_excuse_task, inquiry.id, request_id_of(request))
    return inquiry_out(inquiry, all_medicines(db), True)


@app.patch("/inquiries/{inquiry_id}/cancel", response_model=InquiryOut)
def cancel_inquiry(inquiry_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """Cancel an open inquiry. If medicine was set aside, it goes back into stock."""
    actor = actor_of(request)
    inquiry = locked_inquiry(db, inquiry_id)
    ensure_inquiry_access(inquiry, actor)
    if inquiry.status not in ("pending", "ready"):
        raise ApiError(409, "INVALID_STATE", f"A {inquiry.status} inquiry cannot be cancelled")
    if inquiry.status == "ready" and inquiry.medicine_id and inquiry.quantity:
        locked_medicine(db, inquiry.medicine_id).stock += inquiry.quantity
    inquiry.status, inquiry.updated_at = "cancelled", now()
    db.commit()
    db.refresh(inquiry)
    return inquiry_out(inquiry, all_medicines(db), actor.role != "student")
