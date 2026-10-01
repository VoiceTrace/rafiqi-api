from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class HomeworkInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class MCQOption(HomeworkInput):
    id: str = Field(..., min_length=1, max_length=10)
    text: str = Field(..., min_length=1)


QuestionFormat = Literal["mcq", "short_note"]


class QuestionInput(HomeworkInput):
    question_text: str = Field(..., min_length=1)
    format: QuestionFormat = "mcq"
    options: list[MCQOption] = Field(default_factory=list, max_length=6)
    correct_answer: str | None = Field(default=None, min_length=1, max_length=10)
    hints: list[str] = Field(default_factory=list, max_length=3)
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
    def valid_hints(cls, hints: list[str]) -> list[str]:
        if any(not hint.strip() for hint in hints):
            raise ValueError("Each hint must be non-empty")
        if any(len(hint) > 500 for hint in hints):
            raise ValueError("Each hint must be at most 500 characters")
        return hints

    @model_validator(mode="after")
    def validate_format(self) -> "QuestionInput":
        if self.format == "mcq":
            if not 2 <= len(self.options) <= 6:
                raise ValueError("MCQ questions need between 2 and 6 options")
            if self.correct_answer not in {option.id for option in self.options}:
                raise ValueError("correct_answer must match an MCQ option")
        elif self.options or self.correct_answer is not None:
            raise ValueError("Short-note questions do not have options or a correct answer")
        return self


class AddQuestionRequest(QuestionInput):
    pass


class UpdateQuestionRequest(HomeworkInput):
    question_text: str | None = Field(default=None, min_length=1)
    format: QuestionFormat | None = None
    options: list[MCQOption] | None = Field(default=None, max_length=6)
    correct_answer: str | None = Field(default=None, min_length=1, max_length=10)
    hints: list[str] | None = Field(default=None, max_length=3)
    concept_ref: str | None = Field(default=None, max_length=200)
    order: int | None = Field(default=None, ge=0)

    @field_validator("options")
    @classmethod
    def unique_option_ids(cls, options: list[MCQOption] | None) -> list[MCQOption] | None:
        return QuestionInput.unique_option_ids(options) if options is not None else options

    @field_validator("hints")
    @classmethod
    def valid_hints(cls, hints: list[str] | None) -> list[str] | None:
        return QuestionInput.valid_hints(hints) if hints is not None else hints


class QuestionRead(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    question_text: str
    format: QuestionFormat
    options: list[MCQOption]
    concept_ref: str | None
    hint_count: int
    revealed_hint_count: int = 0
    # Text of the hints this student has already revealed, in reveal order, so a
    # page reload does not lose hints they have already spent a reveal on.
    revealed_hints: list[str] = Field(default_factory=list)
    order: int


class QuestionReadTeacher(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    question_text: str
    format: QuestionFormat
    options: list[MCQOption]
    correct_answer: str | None
    concept_ref: str | None
    hints: list[str]
    order: int


class CreateAssignmentRequest(HomeworkInput):
    grade_level: str = Field(..., min_length=1, max_length=100)
    subject: str = Field(..., min_length=1, max_length=255)
    chapter: str = Field(..., min_length=1, max_length=255)
    lesson_id: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    due_at: AwareDatetime | None = None


class UpdateAssignmentRequest(HomeworkInput):
    grade_level: str | None = Field(default=None, min_length=1, max_length=100)
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    chapter: str | None = Field(default=None, min_length=1, max_length=255)
    lesson_id: str | None = Field(default=None, min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    due_at: AwareDatetime | None = None


class DistributeRequest(BaseModel):
    due_at: AwareDatetime | None = None


class AssignmentRead(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    teacher_id: uuid.UUID
    grade_level: str
    subject: str
    chapter: str
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


class StudentAssignmentRead(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    grade_level: str
    subject: str
    chapter: str
    lesson_id: str
    title: str
    description: str | None
    status: str
    score: float | None
    due_at: datetime | None
    submitted_at: datetime | None
    question_count: int = 0


class StudentAssignmentWithQuestions(StudentAssignmentRead):
    questions: list[QuestionRead]


class AnswerInput(HomeworkInput):
    question_id: uuid.UUID
    answer: str = Field(..., min_length=1, max_length=5000)


class SubmitHomeworkRequest(BaseModel):
    answers: list[AnswerInput] = Field(..., min_length=1)

    @field_validator("answers")
    @classmethod
    def unique_questions(cls, answers: list[AnswerInput]) -> list[AnswerInput]:
        if len({answer.question_id for answer in answers}) != len(answers):
            raise ValueError("Each question must be answered exactly once")
        return answers


class HintRevealRead(BaseModel):
    question_id: uuid.UUID
    hint_index: int
    hint: str


class AttemptResult(BaseModel):
    question_id: uuid.UUID
    answer: str
    teacher_score: float | None = None
    teacher_comment: str | None = None


class SubmissionResult(BaseModel):
    student_assignment_id: uuid.UUID
    status: str
    score: float | None = None
    results: list[AttemptResult] = Field(default_factory=list)


class GradeAnswerInput(HomeworkInput):
    question_id: uuid.UUID
    score: float = Field(..., ge=0, le=1)
    comment: str | None = Field(default=None, max_length=2000)


class GradeSubmissionRequest(BaseModel):
    grades: list[GradeAnswerInput] = Field(..., min_length=1)
    approve: bool = False

    @field_validator("grades")
    @classmethod
    def unique_questions(cls, grades: list[GradeAnswerInput]) -> list[GradeAnswerInput]:
        if len({grade.question_id for grade in grades}) != len(grades):
            raise ValueError("Each question can be graded only once")
        return grades


class TeacherAttemptRead(BaseModel):
    question_id: uuid.UUID
    question_text: str
    format: QuestionFormat
    answer: str
    correct_answer: str | None
    hints_revealed: int
    teacher_score: float | None
    teacher_comment: str | None


class TeacherSubmissionRead(BaseModel):
    student_assignment_id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    status: str
    score: float | None
    submitted_at: datetime | None
    approved_at: datetime | None
    attempts: list[TeacherAttemptRead]


class ConceptGap(BaseModel):
    concept_ref: str
    avg_mastery: float
    student_count: int
    confidence: str


class GapDigestRead(BaseModel):
    lesson_id: str
    student_coverage: int
    total_students: int
    coverage_sufficient: bool
    gaps: list[ConceptGap]
