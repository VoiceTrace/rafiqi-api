from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class HomeworkInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


# ── Options ────────────────────────────────────────────────────────────────────

class MCQOption(HomeworkInput):
    id: str = Field(..., min_length=1, max_length=10)
    text: str = Field(..., min_length=1)


# ── Question ──────────────────────────────────────────────────────────────────

class AddQuestionRequest(HomeworkInput):
    question_text: str = Field(..., min_length=1)
    options: list[MCQOption] = Field(..., min_length=2, max_length=6)
    correct_answer: str = Field(..., min_length=1, max_length=10)
    hints: list[str] = Field(..., min_length=3, max_length=3)
    concept_ref: str | None = Field(default=None, max_length=200)
    order: int = Field(default=0, ge=0)

    @field_validator("options")
    @classmethod
    def unique_option_ids(cls, options: list[MCQOption]) -> list[MCQOption]:
        if len({option.id for option in options}) != len(options):
            raise ValueError("Option ids must be unique")
        return options

    @field_validator("hints")
    @classmethod
    def three_nonempty_hints(cls, hints: list[str]) -> list[str]:
        if any(not hint.strip() for hint in hints):
            raise ValueError("Each hint must be non-empty")
        if any(len(hint) > 500 for hint in hints):
            raise ValueError("Each hint must be at most 500 characters")
        return hints


class UpdateQuestionRequest(HomeworkInput):
    question_text: str | None = Field(default=None, min_length=1)
    options: list[MCQOption] | None = Field(default=None, min_length=2, max_length=6)
    correct_answer: str | None = Field(default=None, min_length=1, max_length=10)
    hints: list[str] | None = Field(default=None, min_length=3, max_length=3)
    concept_ref: str | None = Field(default=None, max_length=200)
    order: int | None = Field(default=None, ge=0)

    @field_validator("options")
    @classmethod
    def unique_option_ids(cls, options: list[MCQOption] | None) -> list[MCQOption] | None:
        if options is not None:
            return AddQuestionRequest.unique_option_ids(options)
        return options

    @field_validator("hints")
    @classmethod
    def three_nonempty_hints(cls, hints: list[str] | None) -> list[str] | None:
        if hints is not None:
            return AddQuestionRequest.three_nonempty_hints(hints)
        return hints


class QuestionRead(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    question_text: str
    format: str
    options: list[MCQOption]
    concept_ref: str | None
    hints: list[str]
    order: int
    # correct_answer intentionally omitted — never sent to student


class QuestionReadTeacher(QuestionRead):
    """Teacher-only view: includes correct_answer."""
    correct_answer: str


# ── Assignment ────────────────────────────────────────────────────────────────

class CreateAssignmentRequest(HomeworkInput):
    lesson_id: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    due_at: AwareDatetime | None = None


class UpdateAssignmentRequest(HomeworkInput):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    due_at: AwareDatetime | None = None


class DistributeRequest(BaseModel):
    student_ids: list[uuid.UUID] = Field(..., min_length=1)
    due_at: AwareDatetime | None = None

    @field_validator("student_ids")
    @classmethod
    def unique_students(cls, ids: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(ids)) != len(ids):
            raise ValueError("Student ids must be unique")
        return ids


class AssignmentRead(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    teacher_id: uuid.UUID
    lesson_id: str
    title: str
    description: str | None
    status: str
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    question_count: int = 0


class AssignmentWithQuestions(AssignmentRead):
    questions: list[QuestionReadTeacher]


# ── Student-facing ────────────────────────────────────────────────────────────

class StudentAssignmentRead(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    lesson_id: str
    title: str
    description: str | None
    status: str
    score: float | None
    due_at: datetime | None
    submitted_at: datetime | None
    question_count: int = 0


class StudentAssignmentWithQuestions(StudentAssignmentRead):
    """Student view: questions WITHOUT correct_answer."""
    questions: list[QuestionRead]


# ── Submission ────────────────────────────────────────────────────────────────

class AnswerInput(BaseModel):
    question_id: uuid.UUID
    selected_option: str = Field(..., min_length=1, max_length=10)


class SubmitHomeworkRequest(BaseModel):
    answers: list[AnswerInput] = Field(..., min_length=1)

    @field_validator("answers")
    @classmethod
    def unique_questions(cls, answers: list[AnswerInput]) -> list[AnswerInput]:
        if len({answer.question_id for answer in answers}) != len(answers):
            raise ValueError("Each question must be answered exactly once")
        return answers


class AttemptResult(BaseModel):
    question_id: uuid.UUID
    selected_option: str
    is_correct: bool
    correctness_score: float
    correct_answer: str  # revealed after submission


class SubmissionResult(BaseModel):
    student_assignment_id: uuid.UUID
    score: float
    correct_count: int
    total_count: int
    results: list[AttemptResult]


# ── Gap digest ────────────────────────────────────────────────────────────────

class ConceptGap(BaseModel):
    concept_ref: str
    avg_mastery: float
    student_count: int
    confidence: str  # forming | developing | solid


class GapDigestRead(BaseModel):
    lesson_id: str
    student_coverage: int
    total_students: int
    coverage_sufficient: bool  # False when below threshold
    gaps: list[ConceptGap]
