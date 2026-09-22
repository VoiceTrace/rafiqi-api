from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── Options ────────────────────────────────────────────────────────────────────

class MCQOption(BaseModel):
    id: str = Field(..., min_length=1, max_length=10)
    text: str = Field(..., min_length=1)


# ── Question ──────────────────────────────────────────────────────────────────

class AddQuestionRequest(BaseModel):
    question_text: str = Field(..., min_length=1)
    options: list[MCQOption] = Field(..., min_length=2, max_length=6)
    correct_answer: str = Field(..., min_length=1, max_length=10)
    concept_ref: str | None = None
    order: int = 0


class UpdateQuestionRequest(BaseModel):
    question_text: str | None = None
    options: list[MCQOption] | None = None
    correct_answer: str | None = None
    concept_ref: str | None = None
    order: int | None = None


class QuestionRead(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    question_text: str
    format: str
    options: list[MCQOption]
    concept_ref: str | None
    order: int
    # correct_answer intentionally omitted — never sent to student


class QuestionReadTeacher(QuestionRead):
    """Teacher-only view: includes correct_answer."""
    correct_answer: str


# ── Assignment ────────────────────────────────────────────────────────────────

class CreateAssignmentRequest(BaseModel):
    lesson_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    due_at: datetime | None = None


class UpdateAssignmentRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    due_at: datetime | None = None


class DistributeRequest(BaseModel):
    student_ids: list[uuid.UUID] = Field(..., min_length=1)
    due_at: datetime | None = None


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
