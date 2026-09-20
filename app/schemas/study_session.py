import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ──────────────────────────────────────────
# Request schemas
# ──────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    lesson_id: str = Field(..., min_length=1, max_length=100)


class PlanSessionRequest(BaseModel):
    """
    lesson_content stub until B1 ships a proper lesson model.
    Expected keys: "objectives" (list[str]), "concepts" (list[str]), "materials" (str?).
    """
    lesson_content: dict
    student_profile: dict | None = None   # optional override; service reads from DB if omitted


class AdvanceStageRequest(BaseModel):
    to_stage: str = Field(..., pattern="^(review|check_in|deepen|wrap_up)$")


class SubmitAttemptRequest(BaseModel):
    student_response: str = Field(..., min_length=1, max_length=5000)


class ExplainRequest(BaseModel):
    concept_ref: str = Field(..., min_length=1, max_length=200)
    student_question: str | None = Field(default=None, max_length=500)
    lesson_context: dict | None = None


# ──────────────────────────────────────────
# Response schemas
# ──────────────────────────────────────────

class SessionRead(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    student_id: uuid.UUID
    lesson_id: str
    status: str
    current_stage: str
    current_concept_index: int
    concepts_order: list[str] | None
    summary_card: dict | None
    started_at: datetime
    closed_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuestionRead(BaseModel):
    """internal_answer_key is intentionally excluded — never sent to the student."""
    id: uuid.UUID
    session_id: uuid.UUID
    concept_ref: str
    stage: str
    question_text: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AttemptRead(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    correctness_score: float
    error_type: str | None
    hint_level: int
    attempt_number: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AttemptResult(BaseModel):
    """Full response returned when a student submits an attempt."""
    attempt: AttemptRead
    feedback: str
    hint_text: str | None            # populated when score < 0.8 and retries remain
    hint_level: int
    concept_confirmed: bool          # True when Rafiqi is confident the concept is mastered
    max_attempts_reached: bool       # True when attempt_number == 3
    session_stage: str               # current stage after this attempt (may have advanced)


class ExplanationRead(BaseModel):
    concept_ref: str
    explanation_text: str


class MasteryRecordRead(BaseModel):
    id: uuid.UUID
    lesson_id: str
    concept_ref: str
    attempt_count: int
    correct_count: int
    mastery_level: float
    dominant_error_type: str | None
    confidence: str
    last_attempt_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SessionWithQuestions(SessionRead):
    questions: list[QuestionRead] = []
