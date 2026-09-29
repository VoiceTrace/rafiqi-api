import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

ResourceType = Literal["question", "article", "link", "image", "video", "file"]

class GradeOut(BaseModel):
    id: str
    title: str

class ClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    grade_id: str

class ClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    grade_id: str
    grade_title: str
    student_count: int

class StudentOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str

class ResourceCreate(BaseModel):
    type: ResourceType
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=8000)
    question: str | None = Field(default=None, max_length=8000)
    answer: str | None = Field(default=None, max_length=8000)
    source_url: HttpUrl | None = None

class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type: ResourceType
    title: str
    description: str
    question: str | None
    answer: str | None
    source_url: str | None
    original_filename: str | None
    media_type: str | None
    byte_size: int | None
    created_at: datetime

class AssignmentCreate(BaseModel):
    class_id: uuid.UUID
    lesson_id: str
    resource_id: uuid.UUID
    required: bool = False

class StudentMaterialOut(BaseModel):
    id: uuid.UUID
    lesson_id: str
    type: ResourceType
    title: str
    description: str
    source_url: str | None
    download_url: str | None
    required: bool
    completed: bool

class CompletionUpdate(BaseModel):
    completed: bool

class CompletionOut(BaseModel):
    assignment_id: uuid.UUID
    completed: bool
    updated_at: datetime
