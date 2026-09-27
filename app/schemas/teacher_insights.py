import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

MasteryBand = Literal["needs_support", "developing", "secure"]
Locale = Literal["en", "ar"]


class MasteryFilterOut(BaseModel):
    subject_id: str
    chapter_id: str | None = None
    lesson_id: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    locale: Locale


class StudentMasteryRow(BaseModel):
    student_id: uuid.UUID
    full_name: str
    avatar_url: str | None
    mastery_score: float | None = Field(default=None, ge=0, le=1)
    mastery_band: MasteryBand | None = None
    concept_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    attempt_count: int = Field(ge=0)
    assisted_evidence_count: int = Field(ge=0)
    dominant_error_type: str | None
    last_attempt_at: datetime | None


class ConceptMasteryOut(BaseModel):
    concept_ref: str
    title: str
    mastery_score: float = Field(ge=0, le=1)
    mastery_band: MasteryBand
    student_count: int = Field(ge=1)
    evidence_count: int = Field(ge=1)
    attempt_count: int = Field(ge=1)
    assisted_evidence_count: int = Field(ge=0)
    dominant_error_type: str | None
    last_attempt_at: datetime


class MasteryBandCounts(BaseModel):
    needs_support: int = Field(ge=0)
    developing: int = Field(ge=0)
    secure: int = Field(ge=0)
    no_evidence: int = Field(ge=0)


class ClassMasteryOut(BaseModel):
    class_id: uuid.UUID
    class_name: str
    filters: MasteryFilterOut
    enrolled_student_count: int = Field(ge=0)
    students_with_evidence: int = Field(ge=0)
    average_mastery: float | None = Field(default=None, ge=0, le=1)
    band_counts: MasteryBandCounts
    students: list[StudentMasteryRow]
    concepts: list[ConceptMasteryOut]
    calculation_version: str = "teacher-evidence-v1"


class StudentMasteryOut(BaseModel):
    class_id: uuid.UUID
    student: StudentMasteryRow
    filters: MasteryFilterOut
    concepts: list[ConceptMasteryOut]
    calculation_version: str = "teacher-evidence-v1"
