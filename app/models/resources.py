"""School-scoped teacher library, class assignment and student progress."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TeacherClass(Base):
    __tablename__ = "teacher_classes"
    __table_args__ = (UniqueConstraint("school_id", "teacher_id", "name", name="uq_teacher_class_name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    grade_id: Mapped[str] = mapped_column(ForeignKey("review_grades.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TeacherClassStudent(Base):
    __tablename__ = "teacher_class_students"
    __table_args__ = (UniqueConstraint("class_id", "student_id", name="uq_class_student"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teacher_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TeacherResource(Base):
    __tablename__ = "teacher_resources"
    __table_args__ = (CheckConstraint("type IN ('question', 'article', 'link', 'image', 'video', 'file')", name="ck_teacher_resource_type"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    question: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    storage_name: Mapped[str | None] = mapped_column(String(255))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str | None] = mapped_column(String(120))
    byte_size: Mapped[int | None] = mapped_column(Integer)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class LessonMaterial(Base):
    __tablename__ = "lesson_materials"
    __table_args__ = (UniqueConstraint("school_id", "class_id", "resource_id", "lesson_id", name="uq_lesson_material_assignment"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teacher_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teacher_resources.id", ondelete="CASCADE"), nullable=False, index=True)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("review_lessons.id", ondelete="CASCADE"), nullable=False, index=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MaterialCompletion(Base):
    __tablename__ = "material_completions"
    __table_args__ = (UniqueConstraint("school_id", "student_id", "lesson_material_id", name="uq_student_material_completion"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    lesson_material_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lesson_materials.id", ondelete="CASCADE"), nullable=False, index=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
