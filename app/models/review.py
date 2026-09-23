"""Permanent per-student lesson review, separate from the legacy Epic D branches."""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ReviewSubject(Base):
    __tablename__ = "review_subjects"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[dict] = mapped_column(JSON, nullable=False)


class ReviewChapter(Base):
    __tablename__ = "review_chapters"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey("review_subjects.id"), nullable=False, index=True)
    title: Mapped[dict] = mapped_column(JSON, nullable=False)


class ReviewLesson(Base):
    __tablename__ = "review_lessons"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(ForeignKey("review_chapters.id"), nullable=False, index=True)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)


class ReviewSession(Base):
    __tablename__ = "review_sessions"
    __table_args__ = (UniqueConstraint("school_id", "student_id", "lesson_id", name="uq_review_student_lesson"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("review_lessons.id"), nullable=False)
    # Snapshot the lesson to keep question IDs/rubrics stable across future catalog edits.
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReviewAttempt(Base):
    __tablename__ = "review_attempts"
    __table_args__ = (
        UniqueConstraint("session_id", "request_id", name="uq_review_attempt_session_request"),
        CheckConstraint("correctness_score >= 0 AND correctness_score <= 1", name="ck_review_attempt_score"),
        CheckConstraint("hint_level >= 0", name="ck_review_attempt_hint_level"),
        CheckConstraint("attempt_number >= 1", name="ck_review_attempt_number"),
        CheckConstraint(
            "error_type IS NULL OR error_type IN ("
            "'force_pair_unequal_magnitude', 'force_pair_missing_reaction', "
            "'force_pair_incomplete_distinct_objects', 'force_pair_missing_distinct_objects', "
            "'balanced_force_means_stopped', 'kinetic_energy_requires_motion', "
            "'equivalent_fraction_denominator_only')",
            name="ck_review_attempt_error_type",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("review_lessons.id"), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    question_id: Mapped[str] = mapped_column(String(100), nullable=False)
    concept_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    option_id: Mapped[str | None] = mapped_column(String(100))
    correctness_score: Mapped[float] = mapped_column(Float, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(100))
    hint_level: Mapped[int] = mapped_column(Integer, nullable=False)
    assisted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    locale: Mapped[str] = mapped_column(String(2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
