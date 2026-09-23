"""Permanent per-student lesson review, separate from the legacy Epic D branches."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
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
