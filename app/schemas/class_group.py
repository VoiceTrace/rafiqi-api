import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClassGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    grade_level: str = Field(min_length=1, max_length=100)
    subject_id: str = Field(min_length=1, max_length=100)
    academic_year: str = Field(min_length=4, max_length=20)


class ClassGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    grade_level: str | None = Field(default=None, min_length=1, max_length=100)
    subject_id: str | None = Field(default=None, min_length=1, max_length=100)
    academic_year: str | None = Field(default=None, min_length=4, max_length=20)
    is_active: bool | None = None


class ClassGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    school_id: uuid.UUID
    teacher_id: uuid.UUID
    name: str
    grade_level: str
    subject_id: str
    academic_year: str
    is_active: bool
    student_count: int = 0
    created_at: datetime
    updated_at: datetime


class EnrollmentCreate(BaseModel):
    student_id: uuid.UUID


class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    class_group_id: uuid.UUID
    student_id: uuid.UUID
    is_active: bool
    enrolled_at: datetime
    updated_at: datetime


class EnrolledStudentOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    avatar_url: str | None
    is_active: bool
    enrollment_id: uuid.UUID
    enrolled_at: datetime
