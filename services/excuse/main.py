import hashlib
import hmac
import io
import logging
import os
import secrets
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import segno
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from db import Base, SessionLocal, get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("excuse")

SIGNING_SECRET = os.environ.get("EXCUSE_SIGNING_SECRET")
if not SIGNING_SECRET:
    raise RuntimeError("EXCUSE_SIGNING_SECRET environment variable is not set")
STUDENT_SERVICE_URL = os.environ.get("STUDENT_SERVICE_URL", "").rstrip("/")
NOTIFICATION_SERVICE_URL = os.environ.get("NOTIFICATION_SERVICE_URL", "").rstrip("/")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "").rstrip("/")     # where the QR code should point (optional)
PUBLIC_API_URL = os.environ.get("PUBLIC_API_URL", "").rstrip("/")  # fallback QR target (optional)
INSTRUCTOR_EMAIL_DOMAIN = os.environ.get("INSTRUCTOR_EMAIL_DOMAIN", "").lower().lstrip("@")  # optional, e.g. school.edu.ph

http = httpx.Client(timeout=httpx.Timeout(90.0, connect=30.0))
MAX_ATTEMPTS = 4

app = FastAPI(title="Excuse & Clearance Service", version="1.0.0")


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
class ExcuseSlip(Base):
    __tablename__ = "excuse_slips"
    __table_args__ = {"schema": "excuse"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consultation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True, nullable=True)
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True, nullable=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    token: Mapped[str] = mapped_column(String, unique=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, default="valid")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_notified: Mapped[bool] = mapped_column(Boolean, default=False)

    recipients: Mapped[list["SlipRecipient"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class Instructor(Base):
    __tablename__ = "instructors"
    __table_args__ = {"schema": "excuse"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SlipRecipient(Base):
    __tablename__ = "slip_recipients"
    __table_args__ = {"schema": "excuse"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slip_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("excuse.excuse_slips.id"))
    instructor_name: Mapped[str] = mapped_column(String)
    instructor_email: Mapped[str] = mapped_column(String)


# ---------- schemas ----------
class ExcuseCreate(BaseModel):
    consultation_id: uuid.UUID | None = None   # the slip comes from a consultation...
    inquiry_id: uuid.UUID | None = None        # ...or from a medicine inquiry (issued at pick-up)
    student_id: uuid.UUID
    rest_days: int = Field(ge=1, le=30)
    issued_on: date | None = None

    @model_validator(mode="after")
    def exactly_one_source(self):
        if (self.consultation_id is None) == (self.inquiry_id is None):
            raise ValueError("provide either consultation_id or inquiry_id")
        return self


class InstructorIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    email: EmailStr
    department: str | None = Field(default=None, max_length=100)


class InstructorBulkIn(BaseModel):
    items: list[InstructorIn] = Field(min_length=1, max_length=200)


class InstructorUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = None
    department: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class InstructorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    full_name: str
    email: str
    department: str | None
    is_active: bool


class NotifyInstructorsIn(BaseModel):
    instructor_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class RecipientIn(BaseModel):
    instructor_name: str = Field(min_length=1, max_length=150)
    instructor_email: EmailStr


class RevokeIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    instructor_name: str
    instructor_email: str


class SlipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    consultation_id: uuid.UUID | None
    inquiry_id: uuid.UUID | None
    student_id: uuid.UUID
    token: str
    valid_from: date
    valid_until: date
    status: str
    effective_status: str = "valid"
    issued_at: datetime
    revoked_at: datetime | None
    revoke_reason: str | None
    student_notified: bool
    recipients: list[RecipientOut]


class VerifyOut(BaseModel):
    status: str                      # valid | expired | revoked
    is_valid: bool
    student_name: str | None
    student_number: str | None
    valid_from: date
    valid_until: date
    issued_at: datetime
    message: str


# ---------- helpers ----------
def today() -> date:
    return datetime.now(timezone.utc).date()


def sign(raw: str) -> str:
    return hmac.new(SIGNING_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()[:20]


def make_token() -> str:
    raw = secrets.token_urlsafe(12)
    return f"{raw}.{sign(raw)}"


def token_is_authentic(token: str) -> bool:
    raw, _, signature = token.partition(".")
    return bool(raw) and bool(signature) and hmac.compare_digest(signature, sign(raw))


def effective_status(slip: ExcuseSlip) -> str:
    if slip.status == "revoked":
        return "revoked"
    return "expired" if today() > slip.valid_until else "valid"


def slip_out(slip: ExcuseSlip) -> SlipOut:
    out = SlipOut.model_validate(slip)
    out.effective_status = effective_status(slip)
    return out


def verification_link(request: Request, token: str) -> str:
    if FRONTEND_URL:
        return f"{FRONTEND_URL}/#/verify/{token}"
    host = request.headers.get("host", request.url.netloc)
    base = PUBLIC_API_URL or f"{request.headers.get('x-forwarded-proto', 'https')}://{host}"
    return f"{base}/excuses/verify/{token}"


def request_id_of(request: Request) -> str:
    return request.headers.get("x-request-id", str(uuid.uuid4()))


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
            log.warning("%s %s %s failed (%s), attempt %d/%d", request_id, method, url, type(exc).__name__, attempt, MAX_ATTEMPTS)
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(2 ** attempt)
            continue
        log.info("%s %s %s -> %s (attempt %d)", request_id, method, url, response.status_code, attempt)
        if response.status_code in retry_statuses and attempt < MAX_ATTEMPTS:
            time.sleep(6 * attempt)
            continue
        return response


def fetch_student(student_id: uuid.UUID, request_id: str) -> dict | None:
    if not STUDENT_SERVICE_URL:
        return None
    try:
        response = call("GET", f"{STUDENT_SERVICE_URL}/students/{student_id}", request_id)
    except httpx.HTTPError:
        return None
    return response.json() if response.status_code == 200 else None


def send_notification(email: str, kind: str, subject: str, text: str, related_id: uuid.UUID, request_id: str) -> bool:
    if not NOTIFICATION_SERVICE_URL:
        return False
    try:
        response = call("POST", f"{NOTIFICATION_SERVICE_URL}/notifications", request_id,
                        json={"recipient_email": email, "type": kind, "subject": subject, "body": text,
                              "related_id": str(related_id)})
    except httpx.HTTPError as exc:
        log.warning("%s could not reach notification service (%s)", request_id, type(exc).__name__)
        return False
    return 200 <= response.status_code < 300


def notify_student_task(slip_id: uuid.UUID, link: str, request_id: str) -> None:
    """Runs after the response is sent, so a sleeping Notification service never slows down the clinic."""
    with SessionLocal() as db:
        slip = db.get(ExcuseSlip, slip_id)
        if not slip:
            return
        student = fetch_student(slip.student_id, request_id)
        if not student:
            log.warning("%s cannot notify: student %s not found or unreachable", request_id, slip.student_id)
            return
        text = (f"Hello {student['full_name']},\n\nA medical excuse slip has been issued for you, valid from "
                f"{slip.valid_from.isoformat()} to {slip.valid_until.isoformat()}.\n"
                f"Instructors can verify it here: {link}\n\nSchool Clinic")
        if send_notification(student["email"], "excuse_issued", "Your medical excuse slip", text, slip.id, request_id):
            slip.student_notified = True
            db.commit()


def notify_instructor_task(slip_id: uuid.UUID, recipient_id: uuid.UUID, link: str, request_id: str) -> None:
    with SessionLocal() as db:
        slip = db.get(ExcuseSlip, slip_id)
        recipient = db.get(SlipRecipient, recipient_id)
        if not slip or not recipient:
            return
        student = fetch_student(slip.student_id, request_id)
        who = f"{student['full_name']} ({student['student_number']})" if student else "a student"
        text = (f"Hello {recipient.instructor_name},\n\nThe school clinic has issued a medical excuse for {who}, "
                f"valid from {slip.valid_from.isoformat()} to {slip.valid_until.isoformat()}.\n"
                f"Verify it here: {link}\n\nSchool Clinic")
        send_notification(recipient.instructor_email, "excuse_instructor", "Medical excuse notice", text, slip.id, request_id)


def find_existing(db: Session, payload: "ExcuseCreate") -> ExcuseSlip | None:
    if payload.consultation_id:
        return db.scalar(select(ExcuseSlip).where(ExcuseSlip.consultation_id == payload.consultation_id))
    return db.scalar(select(ExcuseSlip).where(ExcuseSlip.inquiry_id == payload.inquiry_id))


def check_domain(email: str) -> None:
    if INSTRUCTOR_EMAIL_DOMAIN and not email.lower().endswith("@" + INSTRUCTOR_EMAIL_DOMAIN):
        raise ApiError(422, "INVALID_EMAIL_DOMAIN", f"Instructor emails must end with @{INSTRUCTOR_EMAIL_DOMAIN}")


def get_slip(db: Session, slip_id: uuid.UUID) -> ExcuseSlip:
    slip = db.get(ExcuseSlip, slip_id)
    if not slip:
        raise HTTPException(status_code=404, detail="Excuse slip not found")
    return slip


# ---------- endpoints ----------
@app.get("/health")
def health():
    return {"status": "ok", "service": "excuse"}


@app.post("/excuses", response_model=SlipOut, status_code=201)
def create_excuse(payload: ExcuseCreate, request: Request, response: Response,
                  background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Internal: called by the Consultation service. Repeating the call returns the same slip."""
    existing = find_existing(db, payload)
    if existing:
        response.status_code = 200
        return slip_out(existing)
    issued_on = payload.issued_on or today()
    slip = ExcuseSlip(consultation_id=payload.consultation_id, inquiry_id=payload.inquiry_id,
                      student_id=payload.student_id, token=make_token(),
                      valid_from=issued_on, valid_until=issued_on + timedelta(days=payload.rest_days - 1))
    db.add(slip)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = find_existing(db, payload)
        if existing:
            response.status_code = 200
            return slip_out(existing)
        raise ApiError(409, "CONFLICT", "The slip could not be created")
    db.refresh(slip)
    background_tasks.add_task(notify_student_task, slip.id, verification_link(request, slip.token), request_id_of(request))
    return slip_out(slip)


@app.get("/excuses", response_model=list[SlipOut])
def list_slips(
    student_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(valid|revoked)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(ExcuseSlip)
    if student_id:
        stmt = stmt.where(ExcuseSlip.student_id == student_id)
    if status:
        stmt = stmt.where(ExcuseSlip.status == status)
    rows = db.scalars(stmt.order_by(ExcuseSlip.issued_at.desc()).limit(limit).offset(offset)).all()
    return [slip_out(s) for s in rows]


@app.get("/excuses/verify/{token}", response_model=VerifyOut)
def verify(token: str, request: Request, db: Session = Depends(get_db)):
    """Public: anyone who scans the QR code. Shows validity only, never medical details."""
    if not token_is_authentic(token):
        raise ApiError(404, "INVALID_TOKEN", "This code is not a valid excuse slip")
    slip = db.scalar(select(ExcuseSlip).where(ExcuseSlip.token == token))
    if not slip:
        raise ApiError(404, "INVALID_TOKEN", "This code is not a valid excuse slip")
    status = effective_status(slip)
    student = fetch_student(slip.student_id, request_id_of(request))
    message = {
        "valid": "This medical excuse is valid.",
        "expired": "This medical excuse has expired.",
        "revoked": "This medical excuse was revoked by the clinic.",
    }[status]
    return VerifyOut(status=status, is_valid=status == "valid",
                     student_name=student["full_name"] if student else None,
                     student_number=student["student_number"] if student else None,
                     valid_from=slip.valid_from, valid_until=slip.valid_until,
                     issued_at=slip.issued_at, message=message)


@app.get("/excuses/{slip_id}", response_model=SlipOut)
def read_slip(slip_id: uuid.UUID, db: Session = Depends(get_db)):
    return slip_out(get_slip(db, slip_id))


@app.get("/excuses/{slip_id}/qr")
def slip_qr(slip_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    slip = get_slip(db, slip_id)
    buffer = io.BytesIO()
    segno.make(verification_link(request, slip.token), error="m").save(buffer, kind="svg", scale=6, border=2)
    return Response(content=buffer.getvalue(), media_type="image/svg+xml")


@app.patch("/excuses/{slip_id}/revoke", response_model=SlipOut)
def revoke_slip(slip_id: uuid.UUID, payload: RevokeIn, db: Session = Depends(get_db)):
    slip = get_slip(db, slip_id)
    if slip.status == "revoked":
        raise ApiError(409, "INVALID_STATE", "This slip is already revoked")
    slip.status, slip.revoked_at, slip.revoke_reason = "revoked", datetime.now(timezone.utc), payload.reason
    db.commit()
    db.refresh(slip)
    return slip_out(slip)


@app.post("/excuses/{slip_id}/recipients", response_model=SlipOut, status_code=201)
def add_recipient(slip_id: uuid.UUID, payload: RecipientIn, request: Request,
                  background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Add an instructor to inform. They are notified right away."""
    slip = get_slip(db, slip_id)
    if slip.status == "revoked":
        raise ApiError(409, "INVALID_STATE", "A revoked slip cannot be sent to instructors")
    recipient = SlipRecipient(slip_id=slip.id, instructor_name=payload.instructor_name,
                              instructor_email=payload.instructor_email)
    db.add(recipient)
    db.commit()
    db.refresh(slip)
    background_tasks.add_task(notify_instructor_task, slip.id, recipient.id,
                              verification_link(request, slip.token), request_id_of(request))
    return slip_out(slip)


@app.post("/excuses/{slip_id}/notify-student", response_model=SlipOut)
def notify_student_again(slip_id: uuid.UUID, request: Request, background_tasks: BackgroundTasks,
                         db: Session = Depends(get_db)):
    slip = get_slip(db, slip_id)
    background_tasks.add_task(notify_student_task, slip.id, verification_link(request, slip.token), request_id_of(request))
    return slip_out(slip)


# ---------- instructors (filled in once, then picked from a list) ----------
@app.get("/instructors", response_model=list[InstructorOut])
def list_instructors(q: str | None = None, active_only: bool = True,
                     limit: int = Query(default=200, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(Instructor)
    if active_only:
        stmt = stmt.where(Instructor.is_active.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Instructor.full_name.ilike(like) | Instructor.email.ilike(like) | Instructor.department.ilike(like))
    return db.scalars(stmt.order_by(Instructor.full_name).limit(limit)).all()


@app.post("/instructors", response_model=InstructorOut, status_code=201)
def create_instructor(payload: InstructorIn, db: Session = Depends(get_db)):
    check_domain(payload.email)
    instructor = Instructor(full_name=payload.full_name.strip(), email=payload.email.lower(),
                            department=(payload.department or None))
    db.add(instructor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "CONFLICT", "An instructor with this email already exists")
    db.refresh(instructor)
    return instructor


@app.post("/instructors/bulk")
def create_instructors_bulk(payload: InstructorBulkIn, db: Session = Depends(get_db)):
    """Add many instructors at once. Emails that already exist, or do not match the school domain, are skipped."""
    existing = {e.lower() for e in db.scalars(select(Instructor.email)).all()}
    created, skipped = 0, []
    for item in payload.items:
        email = item.email.lower()
        if email in existing or (INSTRUCTOR_EMAIL_DOMAIN and not email.endswith("@" + INSTRUCTOR_EMAIL_DOMAIN)):
            skipped.append(email)
            continue
        db.add(Instructor(full_name=item.full_name.strip(), email=email, department=item.department or None))
        existing.add(email)
        created += 1
    db.commit()
    return {"created": created, "skipped": skipped}


@app.put("/instructors/{instructor_id}", response_model=InstructorOut)
def update_instructor(instructor_id: uuid.UUID, payload: InstructorUpdate, db: Session = Depends(get_db)):
    instructor = db.get(Instructor, instructor_id)
    if not instructor:
        raise HTTPException(status_code=404, detail="Instructor not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("email"):
        check_domain(data["email"])
        data["email"] = data["email"].lower()
    for field, value in data.items():
        setattr(instructor, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "CONFLICT", "An instructor with this email already exists")
    db.refresh(instructor)
    return instructor


@app.post("/excuses/{slip_id}/notify-instructors", response_model=SlipOut)
def notify_instructors(slip_id: uuid.UUID, payload: NotifyInstructorsIn, request: Request,
                       background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Send the slip to instructors picked from the list. Instructors who already received it are skipped."""
    slip = get_slip(db, slip_id)
    if slip.status == "revoked":
        raise ApiError(409, "INVALID_STATE", "A revoked slip cannot be sent to instructors")
    instructors = db.scalars(select(Instructor).where(Instructor.id.in_(payload.instructor_ids),
                                                      Instructor.is_active.is_(True))).all()
    if not instructors:
        raise ApiError(422, "NO_INSTRUCTORS", "None of the selected instructors could be found")
    already = {r.instructor_email.lower() for r in slip.recipients}
    added = []
    for instructor in instructors:
        if instructor.email.lower() in already:
            continue
        recipient = SlipRecipient(slip_id=slip.id, instructor_name=instructor.full_name, instructor_email=instructor.email)
        db.add(recipient)
        added.append(recipient)
    db.commit()
    db.refresh(slip)
    link = verification_link(request, slip.token)
    for recipient in added:
        background_tasks.add_task(notify_instructor_task, slip.id, recipient.id, link, request_id_of(request))
    return slip_out(slip)
