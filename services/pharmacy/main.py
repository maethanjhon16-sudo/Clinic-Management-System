import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from db import Base, get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pharmacy")

app = FastAPI(title="Pharmacy Service", version="1.0.0")


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


class MedicineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    unit: str | None = Field(default=None, max_length=30)
    reorder_level: int | None = Field(default=None, ge=0, le=1_000_000)
    expiry_date: date | None = None


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
