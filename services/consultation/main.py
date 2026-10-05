import logging
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from db import Base, get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("consultation")

APPOINTMENT_SERVICE_URL = os.environ.get("APPOINTMENT_SERVICE_URL", "").rstrip("/")
PHARMACY_SERVICE_URL = os.environ.get("PHARMACY_SERVICE_URL", "").rstrip("/")  # optional until Pharmacy exists
EXCUSE_SERVICE_URL = os.environ.get("EXCUSE_SERVICE_URL", "").rstrip("/")      # optional until Excuse exists

# Free hosts sleep idle services (about 1 minute to wake), so allow long waits and retry.
http = httpx.Client(timeout=httpx.Timeout(90.0, connect=30.0))
MAX_ATTEMPTS = 4
EVENT_ORDER = {"appointment": 0, "pharmacy": 1, "excuse": 2}

app = FastAPI(title="Consultation Service", version="1.0.0")


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
class Consultation(Base):
    __tablename__ = "consultations"
    __table_args__ = {"schema": "consultation"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    appointment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_excuse: Mapped[bool] = mapped_column(Boolean, default=False)
    rest_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prescriptions: Mapped[list["Prescription"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    events: Mapped[list["IntegrationEvent"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class Prescription(Base):
    __tablename__ = "prescriptions"
    __table_args__ = {"schema": "consultation"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consultation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("consultation.consultations.id"))
    medicine_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    quantity: Mapped[int] = mapped_column(Integer)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)


class IntegrationEvent(Base):
    __tablename__ = "integration_events"
    __table_args__ = {"schema": "consultation"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consultation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("consultation.consultations.id"))
    target: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- schemas ----------
class PrescriptionIn(BaseModel):
    medicine_id: uuid.UUID
    quantity: int = Field(gt=0, le=1000)
    instructions: str | None = Field(default=None, max_length=500)


class ConsultationCreate(BaseModel):
    appointment_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=2000)
    needs_excuse: bool = False
    rest_days: int | None = Field(default=None, ge=1, le=30)
    prescriptions: list[PrescriptionIn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def rest_days_required_for_excuse(self):
        if self.needs_excuse and self.rest_days is None:
            raise ValueError("rest_days is required when needs_excuse is true")
        return self


class PrescriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    medicine_id: uuid.UUID
    quantity: int
    instructions: str | None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    target: str
    status: str
    attempts: int
    last_error: str | None
    updated_at: datetime


class ConsultationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    appointment_id: uuid.UUID
    student_id: uuid.UUID
    doctor_id: uuid.UUID
    notes: str | None
    needs_excuse: bool
    rest_days: int | None
    completed_at: datetime
    prescriptions: list[PrescriptionOut]
    events: list[EventOut]
    integration_status: str = "pending"


def to_out(c: Consultation) -> ConsultationOut:
    out = ConsultationOut.model_validate(c)
    out.events.sort(key=lambda e: EVENT_ORDER.get(e.target, 99))
    out.integration_status = "complete" if all(e.status == "success" for e in out.events) else "incomplete"
    return out


# ---------- helpers ----------
def now() -> datetime:
    return datetime.now(timezone.utc)


def request_id_of(request: Request) -> str:
    return request.headers.get("x-request-id", str(uuid.uuid4()))


def call(method: str, url: str, request_id: str, json=None) -> httpx.Response:
    """HTTP call with retries for sleeping services. POST/PATCH are only retried when the request was surely not processed."""
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


def fetch_appointment(appointment_id: uuid.UUID, request_id: str) -> dict:
    """Integration point: the consultation must belong to a real, still-scheduled appointment."""
    if not APPOINTMENT_SERVICE_URL:
        raise ApiError(503, "SERVICE_NOT_CONFIGURED", "APPOINTMENT_SERVICE_URL is not configured")
    try:
        response = call("GET", f"{APPOINTMENT_SERVICE_URL}/appointments/{appointment_id}", request_id)
    except httpx.HTTPError as exc:
        raise ApiError(503, "APPOINTMENT_SERVICE_UNAVAILABLE", "The appointments service is not responding",
                       {"request_id": request_id, "reason": type(exc).__name__})
    if response.status_code == 404:
        raise ApiError(422, "INVALID_APPOINTMENT", "The appointment does not exist")
    if response.status_code != 200:
        raise ApiError(502, "APPOINTMENT_SERVICE_ERROR", f"The appointments service returned status {response.status_code}")
    appointment = response.json()
    if appointment.get("status") != "scheduled":
        raise ApiError(409, "INVALID_STATE", f"The appointment is already {appointment.get('status')}")
    return appointment


# ----- follow-up actions: each returns (status, message) -----
def do_appointment(c: Consultation, request_id: str):
    if not APPOINTMENT_SERVICE_URL:
        return "skipped", "APPOINTMENT_SERVICE_URL is not configured"
    base = f"{APPOINTMENT_SERVICE_URL}/appointments/{c.appointment_id}"
    response = call("PATCH", f"{base}/complete", request_id)
    if response.status_code == 200:
        return "success", None
    if response.status_code == 409:  # maybe an earlier attempt already completed it
        check = call("GET", base, request_id)
        if check.status_code == 200 and check.json().get("status") == "completed":
            return "success", None
    return "failed", f"appointments service returned {response.status_code}: {response.text[:200]}"


def do_pharmacy(c: Consultation, request_id: str):
    if not PHARMACY_SERVICE_URL:
        return "skipped", "PHARMACY_SERVICE_URL is not configured yet"
    payload = {
        "consultation_id": str(c.id),
        "student_id": str(c.student_id),
        "items": [{"prescription_id": str(p.id), "medicine_id": str(p.medicine_id), "quantity": p.quantity}
                  for p in c.prescriptions],
    }
    response = call("POST", f"{PHARMACY_SERVICE_URL}/dispense", request_id, json=payload)
    if 200 <= response.status_code < 300:
        return "success", None
    return "failed", f"pharmacy service returned {response.status_code}: {response.text[:200]}"


def do_excuse(c: Consultation, request_id: str):
    if not EXCUSE_SERVICE_URL:
        return "skipped", "EXCUSE_SERVICE_URL is not configured yet"
    payload = {
        "consultation_id": str(c.id),
        "student_id": str(c.student_id),
        "rest_days": c.rest_days,
        "issued_on": c.completed_at.date().isoformat(),
    }
    response = call("POST", f"{EXCUSE_SERVICE_URL}/excuses", request_id, json=payload)
    if 200 <= response.status_code < 300:
        return "success", None
    return "failed", f"excuse service returned {response.status_code}: {response.text[:200]}"


HANDLERS = {"appointment": do_appointment, "pharmacy": do_pharmacy, "excuse": do_excuse}


def process_events(db: Session, c: Consultation, request_id: str) -> None:
    for event in sorted(c.events, key=lambda e: EVENT_ORDER.get(e.target, 99)):
        if event.status == "success":
            continue
        try:
            status, message = HANDLERS[event.target](c, request_id)
        except httpx.HTTPError as exc:
            status, message = "failed", f"service unreachable ({type(exc).__name__})"
        event.status, event.last_error = status, message
        event.attempts += 1
        event.updated_at = now()
        db.commit()
    db.refresh(c)


def get_consultation(db: Session, consultation_id: uuid.UUID) -> Consultation:
    c = db.get(Consultation, consultation_id)
    if not c:
        raise HTTPException(status_code=404, detail="Consultation not found")
    return c


# ---------- endpoints ----------
@app.get("/health")
def health():
    return {"status": "ok", "service": "consultation"}


@app.post("/consultations", response_model=ConsultationOut, status_code=201)
def create_consultation(payload: ConsultationCreate, request: Request, db: Session = Depends(get_db)):
    request_id = request_id_of(request)
    if db.scalar(select(Consultation.id).where(Consultation.appointment_id == payload.appointment_id)):
        raise ApiError(409, "ALREADY_CONSULTED", "A consultation already exists for this appointment")

    appointment = fetch_appointment(payload.appointment_id, request_id)

    consultation = Consultation(
        appointment_id=payload.appointment_id,
        student_id=uuid.UUID(appointment["student_id"]),   # taken from the appointment, not from the client
        doctor_id=uuid.UUID(appointment["doctor_id"]),
        notes=payload.notes,
        needs_excuse=payload.needs_excuse,
        rest_days=payload.rest_days if payload.needs_excuse else None,
    )
    consultation.prescriptions = [Prescription(**p.model_dump()) for p in payload.prescriptions]
    consultation.events = [IntegrationEvent(target="appointment")]
    if payload.prescriptions:
        consultation.events.append(IntegrationEvent(target="pharmacy"))
    if payload.needs_excuse:
        consultation.events.append(IntegrationEvent(target="excuse"))

    db.add(consultation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "ALREADY_CONSULTED", "A consultation already exists for this appointment")
    db.refresh(consultation)

    # The consultation is saved first; follow-up failures never lose it and can be retried.
    process_events(db, consultation, request_id)
    return to_out(consultation)


@app.get("/consultations", response_model=list[ConsultationOut])
def list_consultations(
    student_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Consultation)
    if student_id:
        stmt = stmt.where(Consultation.student_id == student_id)
    if doctor_id:
        stmt = stmt.where(Consultation.doctor_id == doctor_id)
    rows = db.scalars(stmt.order_by(Consultation.completed_at.desc()).limit(limit).offset(offset)).all()
    return [to_out(c) for c in rows]


@app.get("/consultations/{consultation_id}", response_model=ConsultationOut)
def read_consultation(consultation_id: uuid.UUID, db: Session = Depends(get_db)):
    return to_out(get_consultation(db, consultation_id))


@app.post("/consultations/{consultation_id}/retry", response_model=ConsultationOut)
def retry_followups(consultation_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """Re-run any follow-up (appointment, pharmacy, excuse) that has not succeeded yet."""
    consultation = get_consultation(db, consultation_id)
    process_events(db, consultation, request_id_of(request))
    return to_out(consultation)
