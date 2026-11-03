import logging
import os
import time
import uuid
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, String, func, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from db import Base, get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("appointments")

STUDENT_SERVICE_URL = os.environ.get("STUDENT_SERVICE_URL", "").rstrip("/")
NOTIFICATION_SERVICE_URL = os.environ.get("NOTIFICATION_SERVICE_URL", "").rstrip("/")  # optional

# Clinic schedule (all adjustable with environment variables)
CLINIC_TZ = os.environ.get("CLINIC_TIMEZONE", "Asia/Manila")
TZ = ZoneInfo(CLINIC_TZ)
SLOT_MINUTES = int(os.environ.get("SLOT_MINUTES", "30"))
SLOT_CAPACITY = int(os.environ.get("SLOT_CAPACITY", "1"))            # how many students can be seen at the same time
OPEN_TIME = dtime.fromisoformat(os.environ.get("CLINIC_OPEN", "08:00"))
CLOSE_TIME = dtime.fromisoformat(os.environ.get("CLINIC_CLOSE", "17:00"))
CLINIC_DAYS = {int(d) for d in os.environ.get("CLINIC_DAYS", "0,1,2,3,4").split(",") if d.strip()}  # Monday = 0
MAX_UPCOMING = int(os.environ.get("MAX_UPCOMING_PER_STUDENT", "3"))

# Free hosts sleep idle services (about 1 minute to wake), so allow long waits and retry.
http = httpx.Client(timeout=httpx.Timeout(90.0, connect=90.0))
MAX_ATTEMPTS = 4

app = FastAPI(title="Appointments Service", version="2.0.0")


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


# ---------- who is calling (set by the gateway after it checked the login) ----------
class Actor:
    def __init__(self, role: str | None, student_id: uuid.UUID | None):
        self.role, self.student_id = role, student_id


def actor_of(request: Request) -> Actor:
    raw = request.headers.get("x-student-id")
    try:
        student_id = uuid.UUID(raw) if raw else None
    except ValueError:
        student_id = None
    return Actor(request.headers.get("x-user-role"), student_id)


def request_id_of(request: Request) -> str:
    return request.headers.get("x-request-id", str(uuid.uuid4()))


# ---------- model ----------
class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = {"schema": "appointments"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- schemas ----------
class AppointmentCreate(BaseModel):
    student_id: uuid.UUID
    scheduled_at: datetime
    reason: str | None = Field(default=None, max_length=500)


class AppointmentUpdate(BaseModel):
    scheduled_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    student_id: uuid.UUID
    scheduled_at: datetime
    reason: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class SlotOut(BaseModel):
    start: datetime
    label: str
    available: bool
    remaining: int


class AvailabilityOut(BaseModel):
    day: date
    closed: bool
    message: str | None
    slots: list[SlotOut]


# ---------- helpers ----------
def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def now() -> datetime:
    return datetime.now(timezone.utc)


def clock(t: dtime) -> str:
    return datetime.combine(date.today(), t).strftime("%I:%M %p").lstrip("0")


def check_clinic_hours(when: datetime) -> None:
    local = when.astimezone(TZ)
    if local.weekday() not in CLINIC_DAYS:
        raise ApiError(422, "CLINIC_CLOSED", "The clinic is closed on this day")
    minutes = local.hour * 60 + local.minute
    open_m, close_m = OPEN_TIME.hour * 60 + OPEN_TIME.minute, CLOSE_TIME.hour * 60 + CLOSE_TIME.minute
    if minutes < open_m or minutes + SLOT_MINUTES > close_m:
        raise ApiError(422, "OUTSIDE_HOURS", f"Appointments are available from {clock(OPEN_TIME)} to {clock(CLOSE_TIME)}")
    if (minutes - open_m) % SLOT_MINUTES != 0 or local.second or local.microsecond:
        raise ApiError(422, "INVALID_SLOT", f"Appointments start every {SLOT_MINUTES} minutes")


def lock_slot(db: Session, when: datetime) -> None:
    """Make concurrent bookings for the same time wait for each other, so a slot cannot be oversold."""
    db.execute(text("select pg_advisory_xact_lock(hashtext(:key))"), {"key": when.astimezone(timezone.utc).isoformat()})


def check_capacity(db: Session, when: datetime, exclude_id: uuid.UUID | None = None) -> None:
    stmt = select(func.count()).select_from(Appointment).where(Appointment.scheduled_at == when,
                                                               Appointment.status != "cancelled")
    if exclude_id:
        stmt = stmt.where(Appointment.id != exclude_id)
    if (db.scalar(stmt) or 0) >= SLOT_CAPACITY:
        raise ApiError(409, "SLOT_FULL", "This time is no longer available. Please choose another time.")


def check_student_limits(db: Session, student_id: uuid.UUID, when: datetime, exclude_id: uuid.UUID | None = None,
                         limit_upcoming: bool = True) -> None:
    base = select(func.count()).select_from(Appointment).where(Appointment.student_id == student_id,
                                                               Appointment.status == "scheduled")
    if exclude_id:
        base = base.where(Appointment.id != exclude_id)
    if (db.scalar(base.where(Appointment.scheduled_at == when)) or 0) > 0:
        raise ApiError(409, "DUPLICATE_BOOKING", "This student already has an appointment at this time")
    if limit_upcoming and (db.scalar(base.where(Appointment.scheduled_at > now())) or 0) >= MAX_UPCOMING:
        raise ApiError(409, "LIMIT_REACHED", f"A student can have at most {MAX_UPCOMING} upcoming appointments")


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
    """Integration point: ask the Student service whether this student exists and is active."""
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


def notify_student(student_id: uuid.UUID, kind: str, appointment_id: uuid.UUID, when: datetime, request_id: str) -> None:
    """Background task: tell the student about a booking change. Failures never affect the booking."""
    if not (NOTIFICATION_SERVICE_URL and STUDENT_SERVICE_URL):
        return
    try:
        found = call("GET", f"{STUDENT_SERVICE_URL}/students/{student_id}", request_id)
        if found.status_code != 200:
            return
        student = found.json()
        local = when.astimezone(TZ).strftime("%B %d, %Y at %I:%M %p")
        subject, message = {
            "appointment_confirmed": ("Appointment confirmed", f"Your clinic appointment is confirmed for {local}."),
            "appointment_rescheduled": ("Appointment rescheduled", f"Your clinic appointment was moved to {local}."),
            "appointment_cancelled": ("Appointment cancelled", f"Your clinic appointment on {local} was cancelled."),
        }[kind]
        call("POST", f"{NOTIFICATION_SERVICE_URL}/notifications", request_id,
             json={"recipient_email": student["email"], "type": kind, "subject": subject,
                   "body": f"Hello {student['full_name']},\n\n{message}\n\nSchool Clinic",
                   "related_id": str(appointment_id)})
    except Exception as exc:
        log.warning("%s could not send %s notification: %s", request_id, kind, exc)


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "CONFLICT", "The change conflicts with existing data")


def get_appointment(db: Session, appointment_id: uuid.UUID) -> Appointment:
    appointment = db.get(Appointment, appointment_id)
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment


def ensure_access(appointment: Appointment, actor: Actor) -> None:
    """A student may only touch their own appointments."""
    if actor.role == "student" and (actor.student_id is None or actor.student_id != appointment.student_id):
        raise ApiError(403, "FORBIDDEN", "Students can only manage their own appointments")


# ---------- endpoints ----------
@app.get("/health")
def health():
    return {"status": "ok", "service": "appointments"}


@app.get("/appointments/availability", response_model=AvailabilityOut)
def availability(day: date = Query(alias="date"), db: Session = Depends(get_db)):
    """Which times can still be booked on a given day."""
    if day.weekday() not in CLINIC_DAYS:
        return AvailabilityOut(day=day, closed=True, message="The clinic is closed on this day.", slots=[])
    start = datetime.combine(day, OPEN_TIME, tzinfo=TZ)
    end = datetime.combine(day, CLOSE_TIME, tzinfo=TZ)
    rows = db.execute(
        select(Appointment.scheduled_at, func.count())
        .where(Appointment.status != "cancelled", Appointment.scheduled_at >= start, Appointment.scheduled_at < end)
        .group_by(Appointment.scheduled_at)
    ).all()
    counts = {when: n for when, n in rows}
    slots: list[SlotOut] = []
    current = start
    while current + timedelta(minutes=SLOT_MINUTES) <= end:
        remaining = max(0, SLOT_CAPACITY - counts.get(current, 0))
        slots.append(SlotOut(start=current, label=current.strftime("%I:%M %p").lstrip("0"),
                             available=remaining > 0 and current > now(), remaining=remaining))
        current += timedelta(minutes=SLOT_MINUTES)
    return AvailabilityOut(day=day, closed=False, message=None, slots=slots)


@app.post("/appointments", response_model=AppointmentOut, status_code=201)
def create_appointment(payload: AppointmentCreate, request: Request, background_tasks: BackgroundTasks,
                       db: Session = Depends(get_db)):
    request_id = request_id_of(request)
    actor = actor_of(request)
    if actor.role == "student" and actor.student_id != payload.student_id:
        raise ApiError(403, "FORBIDDEN", "Students can only book appointments for themselves")
    when = aware(payload.scheduled_at)
    if when <= now():
        raise ApiError(422, "PAST_TIME", "The appointment time must be in the future")
    check_clinic_hours(when)
    check_student(payload.student_id, request_id)   # network call first, so no lock is held while waiting
    lock_slot(db, when)
    check_capacity(db, when)
    check_student_limits(db, payload.student_id, when)
    appointment = Appointment(student_id=payload.student_id, scheduled_at=when, reason=payload.reason)
    db.add(appointment)
    commit_or_conflict(db)
    db.refresh(appointment)
    background_tasks.add_task(notify_student, appointment.student_id, "appointment_confirmed", appointment.id,
                              appointment.scheduled_at, request_id)
    return appointment


@app.get("/appointments", response_model=list[AppointmentOut])
def list_appointments(
    request: Request,
    student_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(scheduled|completed|cancelled)$"),
    on_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    actor = actor_of(request)
    if actor.role == "student":
        if actor.student_id is None:
            raise ApiError(403, "FORBIDDEN", "This account is not linked to a student record")
        student_id = actor.student_id
    stmt = select(Appointment)
    if student_id:
        stmt = stmt.where(Appointment.student_id == student_id)
    if status:
        stmt = stmt.where(Appointment.status == status)
    if on_date:
        day_start = datetime.combine(on_date, dtime.min, tzinfo=TZ)
        stmt = stmt.where(Appointment.scheduled_at >= day_start, Appointment.scheduled_at < day_start + timedelta(days=1))
    return db.scalars(stmt.order_by(Appointment.scheduled_at).limit(limit).offset(offset)).all()


@app.get("/appointments/{appointment_id}", response_model=AppointmentOut)
def read_appointment(appointment_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    appointment = get_appointment(db, appointment_id)
    ensure_access(appointment, actor_of(request))
    return appointment


@app.put("/appointments/{appointment_id}", response_model=AppointmentOut)
def reschedule_appointment(appointment_id: uuid.UUID, payload: AppointmentUpdate, request: Request,
                           background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if actor_of(request).role == "student":
        raise ApiError(403, "FORBIDDEN", "Students cannot reschedule. Please cancel and book a new time.")
    appointment = get_appointment(db, appointment_id)
    if appointment.status != "scheduled":
        raise ApiError(409, "INVALID_STATE", f"A {appointment.status} appointment cannot be changed")
    data = payload.model_dump(exclude_unset=True)
    moved = False
    if data.get("scheduled_at"):
        when = aware(data["scheduled_at"])
        if when <= now():
            raise ApiError(422, "PAST_TIME", "The appointment time must be in the future")
        check_clinic_hours(when)
        lock_slot(db, when)
        check_capacity(db, when, exclude_id=appointment.id)
        check_student_limits(db, appointment.student_id, when, exclude_id=appointment.id, limit_upcoming=False)
        appointment.scheduled_at = when
        moved = True
    if "reason" in data:
        appointment.reason = data["reason"]
    appointment.updated_at = now()
    commit_or_conflict(db)
    db.refresh(appointment)
    if moved:
        background_tasks.add_task(notify_student, appointment.student_id, "appointment_rescheduled", appointment.id,
                                  appointment.scheduled_at, request_id_of(request))
    return appointment


def change_status(db: Session, appointment: Appointment, new_status: str) -> Appointment:
    if appointment.status != "scheduled":
        raise ApiError(409, "INVALID_STATE", f"A {appointment.status} appointment cannot be set to {new_status}")
    appointment.status = new_status
    appointment.updated_at = now()
    db.commit()
    db.refresh(appointment)
    return appointment


@app.patch("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(appointment_id: uuid.UUID, request: Request, background_tasks: BackgroundTasks,
                       db: Session = Depends(get_db)):
    appointment = get_appointment(db, appointment_id)
    ensure_access(appointment, actor_of(request))
    appointment = change_status(db, appointment, "cancelled")
    background_tasks.add_task(notify_student, appointment.student_id, "appointment_cancelled", appointment.id,
                              appointment.scheduled_at, request_id_of(request))
    return appointment


@app.patch("/appointments/{appointment_id}/complete", response_model=AppointmentOut)
def complete_appointment(appointment_id: uuid.UUID, db: Session = Depends(get_db)):
    """Internal: called by the Consultation service when a visit is finished."""
    return change_status(db, get_appointment(db, appointment_id), "completed")
