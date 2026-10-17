import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from db import Base, get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notification")

# EMAIL_MODE=log     -> delivery is simulated (written to the log); the default
# EMAIL_MODE=resend  -> real email through the Resend HTTP API (needs RESEND_API_KEY and EMAIL_FROM)
EMAIL_MODE = os.environ.get("EMAIL_MODE", "log").lower()
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
MAX_AUTO_ATTEMPTS = 5

app = FastAPI(title="Notification Service", version="1.0.0")


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


# ---------- model ----------
class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = {"schema": "notification"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipient_email: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column("type", String)
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    related_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------- schemas ----------
class NotificationCreate(BaseModel):
    recipient_email: EmailStr
    type: str = Field(min_length=1, max_length=60)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    related_id: uuid.UUID | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: uuid.UUID
    recipient_email: str
    type: str = Field(validation_alias="kind")
    subject: str
    body: str
    related_id: uuid.UUID | None
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None


# ---------- delivery ----------
def deliver(n: Notification) -> tuple[bool, str | None]:
    if EMAIL_MODE == "resend":
        if not (RESEND_API_KEY and EMAIL_FROM):
            return False, "Resend is not configured (RESEND_API_KEY / EMAIL_FROM)"
        try:
            r = httpx.post("https://api.resend.com/emails", timeout=30,
                           headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                           json={"from": EMAIL_FROM, "to": [n.recipient_email], "subject": n.subject, "text": n.body})
        except httpx.HTTPError as exc:
            return False, f"email provider unreachable ({type(exc).__name__})"
        if r.status_code in (200, 201):
            return True, None
        return False, f"email provider returned {r.status_code}: {r.text[:200]}"

    # Simulated delivery. Addresses ending in @fail.test fail on the first attempt so you can demo retries.
    if n.recipient_email.lower().endswith("@fail.test") and n.attempts == 0:
        return False, "simulated delivery failure"
    log.info("SIMULATED EMAIL to=%s subject=%s", n.recipient_email, n.subject)
    return True, None


def attempt_delivery(db: Session, n: Notification) -> Notification:
    ok, error = deliver(n)
    n.attempts += 1
    if ok:
        n.status, n.last_error, n.sent_at = "sent", None, datetime.now(timezone.utc)
    else:
        n.status, n.last_error = "failed", error
        log.warning("notification %s failed (attempt %d): %s", n.id, n.attempts, error)
    db.commit()
    db.refresh(n)
    return n


def get_notification(db: Session, notification_id: uuid.UUID) -> Notification:
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    return n


# ---------- endpoints ----------
@app.get("/health")
def health():
    return {"status": "ok", "service": "notification", "email_mode": EMAIL_MODE}


@app.post("/notifications", response_model=NotificationOut, status_code=201)
def create_notification(payload: NotificationCreate, db: Session = Depends(get_db)):
    """Internal: called by the other services. The record is stored first, then delivery is attempted."""
    n = Notification(recipient_email=payload.recipient_email, kind=payload.type, subject=payload.subject,
                     body=payload.body, related_id=payload.related_id, status="pending")
    db.add(n)
    db.commit()
    db.refresh(n)
    return attempt_delivery(db, n)


@app.get("/notifications/summary")
def summary(db: Session = Depends(get_db)):
    rows = db.execute(select(Notification.status, func.count()).group_by(Notification.status)).all()
    counts = {status: count for status, count in rows}
    return {"sent": counts.get("sent", 0), "failed": counts.get("failed", 0), "pending": counts.get("pending", 0)}


@app.post("/notifications/retry-failed")
def retry_failed(db: Session = Depends(get_db)):
    """Retry every failed or pending notification that has not used up its automatic attempts."""
    rows = db.scalars(
        select(Notification).where(Notification.status.in_(["failed", "pending"]),
                                   Notification.attempts < MAX_AUTO_ATTEMPTS)
        .order_by(Notification.created_at).limit(50)
    ).all()
    sent = failed = 0
    for n in rows:
        attempt_delivery(db, n)
        sent, failed = (sent + 1, failed) if n.status == "sent" else (sent, failed + 1)
    return {"retried": len(rows), "sent": sent, "failed": failed}


@app.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    status: str | None = Query(default=None, pattern="^(pending|sent|failed)$"),
    type: str | None = None,
    recipient_email: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Notification)
    if status:
        stmt = stmt.where(Notification.status == status)
    if type:
        stmt = stmt.where(Notification.kind == type)
    if recipient_email:
        stmt = stmt.where(Notification.recipient_email == recipient_email)
    return db.scalars(stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)).all()


@app.get("/notifications/{notification_id}", response_model=NotificationOut)
def read_notification(notification_id: uuid.UUID, db: Session = Depends(get_db)):
    return get_notification(db, notification_id)


@app.post("/notifications/{notification_id}/retry", response_model=NotificationOut)
def retry_notification(notification_id: uuid.UUID, db: Session = Depends(get_db)):
    n = get_notification(db, notification_id)
    if n.status == "sent":
        raise ApiError(409, "ALREADY_SENT", "This notification was already sent")
    return attempt_delivery(db, n)
