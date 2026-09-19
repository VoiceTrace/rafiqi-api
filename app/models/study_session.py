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
    """Taxonomy of error types for Attempt classification. Subject-agnostic for MVP."""
    CONCEPTUAL_GAP = "conceptual_gap"       # doesn't understand the concept
    APPLICATION_ERROR = "application_error" # understands concept, can't apply it
    MISCONCEPTION = "misconception"         # actively wrong mental model
    RECALL_ERROR = "recall_error"           # couldn't remember the fact
    CALCULATION_ERROR = "calculation_error" # process right, arithmetic wrong


class MasteryConfidence(StrEnum):
    FORMING = "forming"         # mastery_level < 0.4
    DEVELOPING = "developing"   # 0.4 <= mastery_level < 0.75
    SOLID = "solid"             # mastery_level >= 0.75


class StudySession(Base):
    """
    One session per student per lesson attempt.
    Multiple sessions on the same lesson are distinguishable and resumable.

    current_stage tracks the session phase (setup → review → check_in → deepen → wrap_up).
    current_concept_index tracks which concept in concepts_order is currently active,
    so sessions survive interruption and can resume exactly where they left off.
    """

    __tablename__ = "study_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # lesson_id stored as string until B1 adds a lessons table; add FK constraint then
    lesson_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SessionStatus.OPEN
    )
    current_stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SessionStage.SETUP
    )
    # Zero-indexed position in concepts_order; drives resumption after interruption
    current_concept_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # Ordered list of concept_refs for this session, e.g. ["newton_3rd_law", "momentum"]
    concepts_order: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Populated at D6 session close — summary shown to student
    summary_card: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # B5 wire-up: warmup response IDs that seeded this session's gap list (nullable until B5 exists)
    gap_seed_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Attempt(Base):
    """
    One row per question-answer exchange during a study session.

    student_response is stored in full so Rafiqi can be trained on real student language
    and so future sessions can give richer context to the LLM.

    correctness_score (0.0–1.0) allows partial credit rather than a binary pass/fail.
    error_type is only meaningful when correctness_score < 0.8; null means correct.
    hint_level records how much help the student needed — signal for mastery_level weighting.
    """

    __tablename__ = "attempts"

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
    lesson_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Must always have a concept reference — never stored without one (D3 hard requirement)
    concept_ref: Mapped[str] = mapped_column(String(200), nullable=False)

    stage: Mapped[str] = mapped_column(String(20), nullable=False)  # AttemptStage

    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    student_response: Mapped[str] = mapped_column(Text, nullable=False)

    # 0.0 = fully wrong, 1.0 = fully correct, 0.5 = partial credit
    correctness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Null when correct (score >= 0.8); set from ErrorType taxonomy otherwise
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 0 = no hint shown, 1 = small hint, 2 = large hint, 3 = answer revealed
    hint_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 1st, 2nd, or 3rd attempt on this concept in this stage
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped["StudySession"] = relationship(back_populates="attempts")


class MasteryRecord(Base):
    """
    Concept-level understanding per student per lesson.
    Not a grade: attempts, outcomes, and the dominant error pattern.
    Populated (and updated) by D6 session close; consumed by Epic E homework generation.

    mastery_level formula (D4 decision):
      weighted_correct = sum(
          1.0 if hint=0 and correct,
          0.7 if hint=1 and correct,
          0.4 if hint=2 and correct,
          0.1 if hint=3 and correct  (answer was revealed)
      ) / attempt_count
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

    # Weighted formula defined in docstring above; drives confidence label
    mastery_level: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Most common error type across all attempts on this concept; null if all correct
    dominant_error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    confidence: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MasteryConfidence.FORMING
    )

    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "school_id", "student_id", "lesson_id", "concept_ref",
            name="uq_mastery_student_lesson_concept",
        ),
    )
