import uuid
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import Boolean, Date, DateTime, Integer, String, func, or_, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from db import Base, get_db

app = FastAPI(title="Student Service", version="1.0.0")


class Student(Base):
    __tablename__ = "students"
    __table_args__ = {"schema": "student"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_number: Mapped[str] = mapped_column(String, unique=True)
    full_name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, unique=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    program: Mapped[str | None] = mapped_column(String, nullable=True)
    year_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_number: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StudentBase(BaseModel):
    student_number: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=1, max_length=150)
    email: EmailStr
    date_of_birth: date | None = None
    program: str | None = None
    year_level: int | None = Field(default=None, ge=1, le=8)
    contact_number: str | None = None


class StudentCreate(StudentBase):
    pass


class StudentUpdate(BaseModel):
    student_number: str | None = Field(default=None, min_length=1, max_length=50)
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = None
    date_of_birth: date | None = None
    program: str | None = None
    year_level: int | None = Field(default=None, ge=1, le=8)
    contact_number: str | None = None


class StudentOut(StudentBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


def error_body(code: str, message: str, details=None) -> dict:
    return {"code": code, "message": message, "details": details}


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    code = {404: "NOT_FOUND", 409: "CONFLICT"}.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(status_code=exc.status_code, content=error_body(code, str(exc.detail)))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "issue": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content=error_body("VALIDATION_ERROR", "Invalid request data", details))


def get_or_404(db: Session, student_id: uuid.UUID) -> Student:
    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


@app.get("/health")
def health():
    return {"status": "ok", "service": "student"}


@app.post("/students", response_model=StudentOut, status_code=201)
def create_student(payload: StudentCreate, db: Session = Depends(get_db)):
    student = Student(**payload.model_dump())
    db.add(student)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Student number or email already exists")
    db.refresh(student)
    return student


@app.get("/students", response_model=list[StudentOut])
def list_students(
    q: str | None = Query(default=None, description="Search name, student number, or email"),
    active_only: bool = True,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Student)
    if active_only:
        stmt = stmt.where(Student.is_active.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Student.full_name.ilike(like), Student.student_number.ilike(like), Student.email.ilike(like)))
    stmt = stmt.order_by(Student.full_name).limit(limit).offset(offset)
    return db.scalars(stmt).all()


@app.get("/students/{student_id}", response_model=StudentOut)
def get_student(student_id: uuid.UUID, db: Session = Depends(get_db)):
    return get_or_404(db, student_id)


@app.put("/students/{student_id}", response_model=StudentOut)
def update_student(student_id: uuid.UUID, payload: StudentUpdate, db: Session = Depends(get_db)):
    student = get_or_404(db, student_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(student, field, value)
    student.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Student number or email already exists")
    db.refresh(student)
    return student


@app.delete("/students/{student_id}", response_model=StudentOut)
def deactivate_student(student_id: uuid.UUID, db: Session = Depends(get_db)):
    student = get_or_404(db, student_id)
    student.is_active = False
    student.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(student)
    return student
