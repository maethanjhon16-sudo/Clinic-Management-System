"""Login, JWT tokens and user management for the API gateway."""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import bcrypt
import jwt
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import Boolean, DateTime, String, create_engine, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

log = logging.getLogger("gateway.auth")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
JWT_SECRET = os.environ.get("JWT_SECRET", "")
TOKEN_HOURS = int(os.environ.get("TOKEN_HOURS", "8"))

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=1) if DATABASE_URL else None
SessionLocal = sessionmaker(bind=engine, autoflush=False) if engine else None
DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt()).decode()


class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "accounts"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    student_id: uuid.UUID | None
    is_active: bool


class LoginIn(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=1, max_length=150)
    role: Literal["admin", "doctor", "nurse", "student"]
    student_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def student_needs_link(self):
        if self.role == "student" and not self.student_id:
            raise ValueError("student_id is required for the student role")
        return self


class ActiveIn(BaseModel):
    is_active: bool


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def make_token(user: User) -> str:
    payload = {
        "sub": str(user.id), "role": user.role, "name": user.full_name,
        "student_id": str(user.student_id) if user.student_id else None,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def read_token(authorization: str | None) -> dict | None:
    """Returns the token payload, or None if there is no valid token."""
    if not authorization or not JWT_SECRET:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def get_db():
    if not SessionLocal:
        raise GatewayError(503, "AUTH_NOT_CONFIGURED", "DATABASE_URL is not configured on the gateway")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_user(authorization: str | None = Header(default=None)) -> dict:
    if not JWT_SECRET:
        raise GatewayError(503, "AUTH_NOT_CONFIGURED", "JWT_SECRET is not configured on the gateway")
    payload = read_token(authorization)
    if not payload:
        raise GatewayError(401, "UNAUTHENTICATED", "Please sign in")
    return payload


def require_admin(user: dict = Depends(require_user)) -> dict:
    if user.get("role") != "admin":
        raise GatewayError(403, "FORBIDDEN", "Only administrators can do this")
    return user


def bootstrap_admin() -> None:
    """Create the first administrator from ADMIN_EMAIL / ADMIN_PASSWORD when no users exist yet."""
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not (SessionLocal and email and password):
        return
    try:
        with SessionLocal() as db:
            if db.scalar(select(func.count()).select_from(User)) == 0:
                db.add(User(email=email, password_hash=hash_password(password), full_name="Administrator", role="admin"))
                db.commit()
                log.info("created the first administrator account")
    except Exception as exc:  # the table may not exist yet
        log.warning("could not create the first administrator: %s", exc)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    if not JWT_SECRET:
        raise GatewayError(503, "AUTH_NOT_CONFIGURED", "JWT_SECRET is not configured on the gateway")
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    stored = user.password_hash if user else DUMMY_HASH  # same work whether or not the email exists
    try:
        matches = bcrypt.checkpw(payload.password.encode()[:72], stored.encode())
    except ValueError:
        matches = False
    if not user or not matches or not user.is_active:
        raise GatewayError(401, "INVALID_CREDENTIALS", "Incorrect email or password")
    return {"access_token": make_token(user), "token_type": "bearer", "user": UserOut.model_validate(user)}


@router.get("/me", response_model=UserOut)
def me(claims: dict = Depends(require_user), db: Session = Depends(get_db)):
    user = db.get(User, uuid.UUID(claims["sub"]))
    if not user or not user.is_active:
        raise GatewayError(401, "UNAUTHENTICATED", "Please sign in")
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(_: dict = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.created_at)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, _: dict = Depends(require_admin), db: Session = Depends(get_db)):
    user = User(email=payload.email.lower(), password_hash=hash_password(payload.password),
                full_name=payload.full_name, role=payload.role, student_id=payload.student_id)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise GatewayError(409, "CONFLICT", "A user with this email already exists")
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def set_active(user_id: uuid.UUID, payload: ActiveIn, admin: dict = Depends(require_admin), db: Session = Depends(get_db)):
    if str(user_id) == admin["sub"] and not payload.is_active:
        raise GatewayError(409, "INVALID_STATE", "You cannot deactivate your own account")
    user = db.get(User, user_id)
    if not user:
        raise GatewayError(404, "NOT_FOUND", "User not found")
    user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return user
