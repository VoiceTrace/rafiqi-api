import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SessionStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class SessionStage(StrEnum):
    SETUP = "setup"
    REVIEW = "review"
    CHECK_IN = "check_in"
    DEEPEN = "deepen"
    WRAP_UP = "wrap_up"


class AttemptStage(StrEnum):
    CHECK_IN = "check_in"
    DEEPEN = "deepen"


class ErrorType(StrEnum):
    CONCEPTUAL_GAP = "conceptual_gap"
    APPLICATION_ERROR = "application_error"
    MISCONCEPTION = "misconception"
    RECALL_ERROR = "recall_error"
    CALCULATION_ERROR = "calculation_error"


class MasteryConfidence(StrEnum):
    FORMING = "forming"       # mastery_level < 0.4
    DEVELOPING = "developing" # 0.4 <= mastery_level < 0.75
    SOLID = "solid"           # mastery_level >= 0.75


class StudySession(Base):
    """
    One per student per lesson attempt. Resumable — current_stage +
    current_concept_index + concepts_order together track exact position.
    """

    __tablename__ = "study_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # String until B1 adds a lessons table; add FK constraint then
    lesson_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SessionStatus.OPEN)
    current_stage: Mapped[str] = mapped_column(String(20), nullable=False, default=SessionStage.SETUP)
    current_concept_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Ordered concept_ref list set by Rafiqi.plan_session(); drives current_concept_index
    concepts_order: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Populated at D6 session close — student-facing summary
    summary_card: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # B5 wire-up: warmup response IDs that seeded gap list (nullable until B5 exists)
    gap_seed_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    questions: Mapped[list["Question"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Question(Base):
    """
    One row per question Rafiqi generates. All retries (Attempts) link back
    to the same Question via FK — no duplication of question_text across retries.
    internal_answer_key is owned by Rafiqi, stored here, and never sent to the student.
    """

    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Must always have a concept reference — never stored without one (D3 hard rule)
    concept_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)  # AttemptStage

    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Owned by Rafiqi — used internally for scoring and hints, never exposed to student
    internal_answer_key: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped["StudySession"] = relationship(back_populates="questions")
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class Attempt(Base):
    """
    One row per student answer. All retries on the same question share one Question
    row via question_id FK.

    correctness_score (0.0–1.0): partial credit, not binary.
    error_type: from ErrorType taxonomy; null when score >= 0.8 (correct).
    hint_level: how much help was shown before this attempt (signal for mastery weighting).
    student_response stored in full for future Rafiqi training context.
    """

    __tablename__ = "attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    student_response: Mapped[str] = mapped_column(Text, nullable=False)

    # 0.0 = fully wrong, 1.0 = fully correct, 0.5 = partial credit
    correctness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Null when correct (score >= 0.8); set from ErrorType taxonomy otherwise
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 0 = no hint shown before this attempt, 3 = answer was revealed
    hint_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Which attempt on this question (1st, 2nd, 3rd)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    question: Mapped["Question"] = relationship(back_populates="attempts")


class MasteryRecord(Base):
    """
    Concept-level understanding per student per lesson.
    Populated at D6 session close by aggregating Attempt → Question → StudySession.
    Consumed by Epic E homework generation.

    mastery_level formula (D4 decision):
      weighted_sum = Σ weight(hint_level) * correctness_score per attempt
      mastery_level = weighted_sum / attempt_count
      weights: hint=0 → 1.0, hint=1 → 0.7, hint=2 → 0.4, hint=3 → 0.1
    Thresholds: < 0.4 → forming, 0.4–0.75 → developing, >= 0.75 → solid
    """

    __tablename__ = "mastery_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lesson_id: Mapped[str] = mapped_column(String(100), nullable=False)
    concept_ref: Mapped[str] = mapped_column(String(200), nullable=False)

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Weighted formula defined in docstring; drives confidence label
    mastery_level: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Most common error type across attempts; null if always correct
    dominant_error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    confidence: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MasteryConfidence.FORMING
    )

    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "school_id", "student_id", "lesson_id", "concept_ref",
            name="uq_mastery_student_lesson_concept",
        ),
    )
