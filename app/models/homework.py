from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class AssignmentStatus(StrEnum):
    draft = "draft"
    distributed = "distributed"
    closed = "closed"


class QuestionFormat(StrEnum):
    mcq = "mcq"
    # RAFIQI_V2: short_answer = "short_answer"
    # RAFIQI_V2: spot_error   = "spot_error"


class StudentAssignmentStatus(StrEnum):
    assigned = "assigned"
    in_progress = "in_progress"
    submitted = "submitted"


class HomeworkAssignment(Base):
    __tablename__ = "homework_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    lesson_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=AssignmentStatus.draft)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # RAFIQI_V2: is_differentiated = False always in v1; set True when Rafiqi
    # generates per-student question sets from MasteryRecord gaps
    # is_differentiated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # PARENT_V2: parent_notification_sent_at scaffold — not populated in v1
    # parent_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    questions: Mapped[list[HomeworkQuestion]] = relationship(
        "HomeworkQuestion", back_populates="assignment",
        cascade="all, delete-orphan", order_by="HomeworkQuestion.order",
    )
    student_assignments: Mapped[list[StudentAssignment]] = relationship(
        "StudentAssignment", back_populates="assignment", cascade="all, delete-orphan",
    )


class HomeworkQuestion(Base):
    __tablename__ = "homework_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("homework_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    # nullable in v1 — required in v2 when Rafiqi targets concepts from MasteryRecord
    concept_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False, default=QuestionFormat.mcq)
    # MCQ: [{"id": "a", "text": "..."}, ...] — 4 options
    options: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    # option id — NEVER sent to student
    correct_answer: Mapped[str] = mapped_column(String(10), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # RAFIQI_V2: progressive hints from Rafiqi
    # hint_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    # hint_2: Mapped[str | None] = mapped_column(Text, nullable=True)

    assignment: Mapped[HomeworkAssignment] = relationship("HomeworkAssignment", back_populates="questions")
    attempts: Mapped[list[HomeworkAttempt]] = relationship(
        "HomeworkAttempt", back_populates="question", cascade="all, delete-orphan",
    )


class StudentAssignment(Base):
    """Junction: which students have received a homework assignment."""
    __tablename__ = "student_assignments"
    __table_args__ = (
        UniqueConstraint("school_id", "student_id", "assignment_id", name="uq_student_assignment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("homework_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=StudentAssignmentStatus.assigned)
    # avg correctness_score across all submitted attempts
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # PARENT_V2: parent_delivery_status scaffold
    # parent_delivery_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # parent_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assignment: Mapped[HomeworkAssignment] = relationship("HomeworkAssignment", back_populates="student_assignments")
    attempts: Mapped[list[HomeworkAttempt]] = relationship(
        "HomeworkAttempt", back_populates="student_assignment", cascade="all, delete-orphan",
    )


class HomeworkAttempt(Base):
    """One row per student per question — recorded on final submission."""
    __tablename__ = "homework_attempts"
    __table_args__ = (
        UniqueConstraint("school_id", "student_id", "question_id", name="uq_homework_attempt"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    student_assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("student_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("homework_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    student_answer: Mapped[str] = mapped_column(String(10), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # THRESHOLD: 0.8 correctness threshold — will be made configurable in v2
    # For MCQ: 1.0 if correct, 0.0 if wrong (binary); threshold checked in service
    correctness_score: Mapped[float] = mapped_column(Float, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    question: Mapped[HomeworkQuestion] = relationship("HomeworkQuestion", back_populates="attempts")
    student_assignment: Mapped[StudentAssignment] = relationship("StudentAssignment", back_populates="attempts")
