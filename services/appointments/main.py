import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, String, and_, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from db import Base, get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("appointments")

STUDENT_SERVICE_URL = os.environ.get("STUDENT_SERVICE_URL", "").rstrip("/")
SLOT_MINUTES = int(os.environ.get("SLOT_MINUTES", "30"))
# Free hosts sleep idle services (about 1 minute to wake), so allow long waits and retry.
http = httpx.Client(timeout=httpx.Timeout(90.0, connect=90.0))
MAX_ATTEMPTS = 4

app = FastAPI(title="Appointments Service", version="1.0.0")


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
class Doctor(Base):
    __tablename__ = "doctors"
    __table_args__ = {"schema": "appointments"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String)
    specialization: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = {"schema": "appointments"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("appointments.doctors.id"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- schemas ----------
class DoctorCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    specialization: str | None = None
    email: EmailStr | None = None


class DoctorUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    specialization: str | None = None
    email: EmailStr | None = None
    is_active: bool | None = None


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    full_name: str
    specialization: str | None
    email: str | None
    is_active: bool
    created_at: datetime


class AppointmentCreate(BaseModel):
    student_id: uuid.UUID
    doctor_id: uuid.UUID
    scheduled_at: datetime
    reason: str | None = Field(default=None, max_length=500)


class AppointmentUpdate(BaseModel):
    scheduled_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    student_id: uuid.UUID
    doctor_id: uuid.UUID
    scheduled_at: datetime
    reason: str | None
    status: str
    created_at: datetime
    updated_at: datetime


# ---------- helpers ----------
def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def now() -> datetime:
    return datetime.now(timezone.utc)


def check_student(student_id: uuid.UUID, request_id: str) -> None:
    """Integration point: ask the Student service whether this student exists and is active."""
    if not STUDENT_SERVICE_URL:
        raise ApiError(503, "SERVICE_NOT_CONFIGURED", "STUDENT_SERVICE_URL is not configured")
    url = f"{STUDENT_SERVICE_URL}/students/{student_id}"
    response = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = http.get(url, headers={"x-request-id": request_id, "accept-encoding": "identity"})
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning("%s student service call failed (%s), attempt %d/%d", request_id, type(exc).__name__, attempt, MAX_ATTEMPTS)
            if attempt == MAX_ATTEMPTS:
                raise ApiError(503, "STUDENT_SERVICE_UNAVAILABLE", "The student service is not responding",
                               {"request_id": request_id, "reason": type(exc).__name__})
            time.sleep(2 ** attempt)
            continue
        log.info("%s GET %s -> %s (attempt %d)", request_id, url, response.status_code, attempt)
        if response.status_code in (502, 503, 504) and attempt < MAX_ATTEMPTS:
            time.sleep(6 * attempt)  # the student service may still be waking up
            continue
        break
    if response.status_code == 404:
        raise ApiError(422, "INVALID_STUDENT", "The student does not exist")
    if response.status_code != 200:
        raise ApiError(502, "STUDENT_SERVICE_ERROR", f"The student service returned status {response.status_code}")
    if not response.json().get("is_active", False):
        raise ApiError(422, "STUDENT_INACTIVE", "The student record is inactive")


def check_doctor(db: Session, doctor_id: uuid.UUID) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise ApiError(422, "INVALID_DOCTOR", "The doctor does not exist")
    if not doctor.is_active:
        raise ApiError(422, "DOCTOR_INACTIVE", "The doctor is not active")
    return doctor


def check_slot(db: Session, doctor_id: uuid.UUID, when: datetime, exclude_id: uuid.UUID | None = None) -> None:
    """Application-level double-booking check (the database unique index is the second line of defence)."""
    if when <= now():
        raise ApiError(422, "PAST_TIME", "The appointment time must be in the future")
    window = timedelta(minutes=SLOT_MINUTES)
    stmt = select(Appointment).where(
        and_(
            Appointment.doctor_id == doctor_id,
            Appointment.status != "cancelled",
            Appointment.scheduled_at > when - window,
            Appointment.scheduled_at < when + window,
        )
    )
    if exclude_id:
        stmt = stmt.where(Appointment.id != exclude_id)
    clash = db.scalars(stmt).first()
    if clash:
        raise ApiError(409, "DOUBLE_BOOKING", f"The doctor already has an appointment within {SLOT_MINUTES} minutes of this time",
                       {"conflicting_appointment_id": str(clash.id), "conflicting_time": clash.scheduled_at.isoformat()})


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        text = str(exc.orig)
        if "uq_doctor_slot" in text:
            raise ApiError(409, "DOUBLE_BOOKING", "The doctor was just booked for this time")
        if "email" in text:
            raise ApiError(409, "CONFLICT", "A doctor with this email already exists")
        raise ApiError(409, "CONFLICT", "The change conflicts with existing data")


def get_appointment(db: Session, appointment_id: uuid.UUID) -> Appointment:
    appointment = db.get(Appointment, appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment


def request_id_of(request: Request) -> str:
    return request.headers.get("x-request-id", str(uuid.uuid4()))


# ---------- health ----------
@app.get("/health")
def health():
    return {"status": "ok", "service": "appointments"}


# ---------- doctors ----------
@app.post("/doctors", response_model=DoctorOut, status_code=201)
def create_doctor(payload: DoctorCreate, db: Session = Depends(get_db)):
    doctor = Doctor(**payload.model_dump())
    db.add(doctor)
    commit_or_conflict(db)
    db.refresh(doctor)
    return doctor


@app.get("/doctors", response_model=list[DoctorOut])
def list_doctors(active_only: bool = True, db: Session = Depends(get_db)):
    stmt = select(Doctor).order_by(Doctor.full_name)
    if active_only:
        stmt = stmt.where(Doctor.is_active.is_(True))
    return db.scalars(stmt).all()


@app.get("/doctors/{doctor_id}", response_model=DoctorOut)
def get_doctor(doctor_id: uuid.UUID, db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doctor


@app.put("/doctors/{doctor_id}", response_model=DoctorOut)
def update_doctor(doctor_id: uuid.UUID, payload: DoctorUpdate, db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(doctor, field, value)
    commit_or_conflict(db)
    db.refresh(doctor)
    return doctor


# ---------- appointments ----------
@app.post("/appointments", response_model=AppointmentOut, status_code=201)
def create_appointment(payload: AppointmentCreate, request: Request, db: Session = Depends(get_db)):
    request_id = request_id_of(request)
    when = aware(payload.scheduled_at)
    check_doctor(db, payload.doctor_id)
    check_student(payload.student_id, request_id)
    check_slot(db, payload.doctor_id, when)
    appointment = Appointment(student_id=payload.student_id, doctor_id=payload.doctor_id,
                              scheduled_at=when, reason=payload.reason)
    db.add(appointment)
    commit_or_conflict(db)
    db.refresh(appointment)
    return appointment


@app.get("/appointments", response_model=list[AppointmentOut])
def list_appointments(
    student_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(scheduled|completed|cancelled)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Appointment)
    if student_id:
        stmt = stmt.where(Appointment.student_id == student_id)
    if doctor_id:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    if status:
        stmt = stmt.where(Appointment.status == status)
    return db.scalars(stmt.order_by(Appointment.scheduled_at).limit(limit).offset(offset)).all()


@app.get("/appointments/{appointment_id}", response_model=AppointmentOut)
def read_appointment(appointment_id: uuid.UUID, db: Session = Depends(get_db)):
    return get_appointment(db, appointment_id)


@app.put("/appointments/{appointment_id}", response_model=AppointmentOut)
def reschedule_appointment(appointment_id: uuid.UUID, payload: AppointmentUpdate, db: Session = Depends(get_db)):
    appointment = get_appointment(db, appointment_id)
    if appointment.status != "scheduled":
        raise ApiError(409, "INVALID_STATE", f"A {appointment.status} appointment cannot be changed")
    data = payload.model_dump(exclude_unset=True)
    if data.get("scheduled_at"):
        when = aware(data["scheduled_at"])
        check_doctor(db, appointment.doctor_id)
        check_slot(db, appointment.doctor_id, when, exclude_id=appointment.id)
        appointment.scheduled_at = when
    if "reason" in data:
        appointment.reason = data["reason"]
    appointment.updated_at = now()
    commit_or_conflict(db)
    db.refresh(appointment)
    return appointment


def change_status(db: Session, appointment_id: uuid.UUID, new_status: str) -> Appointment:
    appointment = get_appointment(db, appointment_id)
    if appointment.status != "scheduled":
        raise ApiError(409, "INVALID_STATE", f"A {appointment.status} appointment cannot be set to {new_status}")
    appointment.status = new_status
    appointment.updated_at = now()
    db.commit()
    db.refresh(appointment)
    return appointment


@app.patch("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(appointment_id: uuid.UUID, db: Session = Depends(get_db)):
    return change_status(db, appointment_id, "cancelled")


@app.patch("/appointments/{appointment_id}/complete", response_model=AppointmentOut)
def complete_appointment(appointment_id: uuid.UUID, db: Session = Depends(get_db)):
    return change_status(db, appointment_id, "completed")
