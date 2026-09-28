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


class ReviewConceptOutcome(BaseModel):
    concept_ref: str
    title: str
    outcome: MasteryBand
    completed_with_support: bool


class TeacherReviewSessionItem(BaseModel):
    session_id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    lesson_id: str
    lesson_title: str
    subject_id: str
    chapter_id: str
    concepts: list[ReviewConceptOutcome]
    total_attempts: int = Field(ge=1)
    dominant_error_type: str | None
    completed_at: datetime


class ReviewSessionPage(BaseModel):
    items: list[TeacherReviewSessionItem]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class TeacherAttemptEvidence(BaseModel):
    id: uuid.UUID
    question_id: str
    concept_ref: str
    response_text: str
    option_id: str | None
    correctness_score: float = Field(ge=0, le=1)
    error_type: str | None
    hint_level: int = Field(ge=0)
    assisted: bool
    attempt_number: int = Field(ge=1)
    locale: Locale
    created_at: datetime


class TeacherReviewSessionDetail(TeacherReviewSessionItem):
    attempts: list[TeacherAttemptEvidence]


class MisconceptionOut(BaseModel):
    error_type: str
    label: str
    concept_ref: str
    student_count: int = Field(ge=1)
    attempt_count: int = Field(ge=1)
    students_with_evidence: int = Field(ge=1)
    percentage: float = Field(ge=0, le=100)
    lesson_ids: list[str]
    last_occurred_at: datetime


class ClassMisconceptionsOut(BaseModel):
    class_id: uuid.UUID
    filters: MasteryFilterOut
    students_with_evidence: int = Field(ge=0)
    items: list[MisconceptionOut]
