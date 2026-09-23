from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

Locale = Literal["en", "ar"]


class CreateReview(BaseModel):
    lesson_id: str = Field(min_length=1, max_length=100)


class ReviewMessage(BaseModel):
    request_id: UUID
    expected_version: int = Field(ge=0)
    action: Literal["chat", "answer", "hint", "help", "next"]
    question_id: str | None = Field(default=None, max_length=100)
    text: str = Field(default="", max_length=2000)
    option_id: str | None = Field(default=None, max_length=100)
    locale: Locale = "en"

    @model_validator(mode="after")
    def validate_payload(self):
        if self.action == "chat" and not self.text.strip():
            raise ValueError("A chat message cannot be empty")
        if self.action == "answer" and not (self.text.strip() or self.option_id):
            raise ValueError("An answer is required")
        if self.action in ("answer", "hint", "next") and not self.question_id:
            raise ValueError("question_id is required")
        return self


class SubjectOut(BaseModel):
    id: str
    title: str


class ChapterOut(SubjectOut):
    subject_id: str


class ConceptOut(SubjectOut):
    description: str


class LessonOut(BaseModel):
    id: str
    title: str
    subject: str
    chapter: str
    objective: str
    key_points: list[str]
    subject_id: str
    chapter_id: str
    concept_refs: list[ConceptOut]


class QuestionOption(BaseModel):
    id: str
    text: str


class QuestionOut(BaseModel):
    """Safe projection of a question — answer keys, keywords and hints are excluded."""
    id: str
    kind: Literal["choice", "written"]
    text: str
    options: list[QuestionOption]
    concept_ref: str | None = None


class SessionOut(BaseModel):
    id: str
    lesson_id: str
    version: int
    lesson: LessonOut
    mock: bool
    complete: bool
    current_question_id: str
    attempts: int
    hint_level: int
    resolved: bool
    can_hint: bool
    total_questions: int
    questions: list[QuestionOut]
    # Transcript entries vary by `kind` (text/question/answer/feedback/hint/action/complete),
    # so they pass through untyped to keep the wire format byte-identical for existing clients.
    messages: list[dict[str, Any]]


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    lesson_id: str
    question_id: str
    concept_ref: str
    response_text: str
    option_id: str | None
    correctness_score: float
    error_type: str | None
    hint_level: int
    assisted: bool
    attempt_number: int
    locale: Locale
    created_at: datetime


class MasteryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    subject_id: str
    concept_ref: str
    mastery_score: float = Field(ge=0, le=1)
    mastery_band: Literal["needs_support", "developing", "secure"]
    evidence_count: int = Field(ge=1)
    attempt_count: int = Field(ge=1)
    assisted_evidence_count: int = Field(ge=0)
    dominant_error_type: str | None
    calculation_version: str
    last_attempt_at: datetime
    updated_at: datetime

