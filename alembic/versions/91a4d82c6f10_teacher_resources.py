"""Grade mappings, teacher resource library, class assignments and completion."""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

revision = "91a4d82c6f10"
down_revision = "83bcb2215849"
branch_labels = None
depends_on = None


def upgrade():
    grades = op.create_table("review_grades", sa.Column("id", sa.String(40), primary_key=True), sa.Column("title", sa.JSON(), nullable=False))
    lesson_grades = op.create_table("review_lesson_grades",
        sa.Column("lesson_id", sa.String(100), sa.ForeignKey("review_lessons.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("grade_id", sa.String(40), sa.ForeignKey("review_grades.id", ondelete="CASCADE"), primary_key=True))
    op.create_index("ix_review_lesson_grades_grade_id", "review_lesson_grades", ["grade_id"])
    classes = op.create_table("teacher_classes",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grade_id", sa.String(40), sa.ForeignKey("review_grades.id"), nullable=False), sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("school_id", "teacher_id", "name", name="uq_teacher_class_name"))
    for col in ("school_id", "teacher_id", "grade_id"):
        op.create_index(f"ix_teacher_classes_{col}", "teacher_classes", [col])
    memberships = op.create_table("teacher_class_students",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", sa.Uuid(), sa.ForeignKey("teacher_classes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("class_id", "student_id", name="uq_class_student"))
    for col in ("school_id", "class_id", "student_id"):
        op.create_index(f"ix_teacher_class_students_{col}", "teacher_class_students", [col])
    resources = op.create_table("teacher_resources",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False), sa.Column("title", sa.String(240), nullable=False), sa.Column("description", sa.Text(), nullable=False),
        sa.Column("question", sa.Text()), sa.Column("answer", sa.Text()), sa.Column("source_url", sa.Text()), sa.Column("storage_name", sa.String(255)),
        sa.Column("original_filename", sa.String(255)), sa.Column("media_type", sa.String(120)), sa.Column("byte_size", sa.Integer()),
        sa.Column("archived_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("type IN ('question', 'article', 'link', 'image', 'video', 'file')", name="ck_teacher_resource_type"))
    for col in ("school_id", "created_by"):
        op.create_index(f"ix_teacher_resources_{col}", "teacher_resources", [col])
    assignments = op.create_table("lesson_materials",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", sa.Uuid(), sa.ForeignKey("teacher_classes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("teacher_resources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.String(100), sa.ForeignKey("review_lessons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("added_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("school_id", "class_id", "resource_id", "lesson_id", name="uq_lesson_material_assignment"))
    for col in ("school_id", "class_id", "resource_id", "lesson_id"):
        op.create_index(f"ix_lesson_materials_{col}", "lesson_materials", [col])
    completions = op.create_table("material_completions",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_material_id", sa.Uuid(), sa.ForeignKey("lesson_materials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("school_id", "student_id", "lesson_material_id", name="uq_student_material_completion"))
    for col in ("school_id", "student_id", "lesson_material_id"):
        op.create_index(f"ix_material_completions_{col}", "material_completions", [col])

    fixture = json.loads((Path(__file__).parent / "fixtures/review-catalog-v2.json").read_text(encoding="utf-8"))
    bind = op.get_bind()
    for table, key in ((grades, "grades"),):
        for row in fixture[key]:
            bind.execute(insert(table).values(**row).on_conflict_do_nothing())
    chapters = sa.table("review_chapters", sa.column("id", sa.String), sa.column("subject_id", sa.String), sa.column("title", sa.JSON))
    for row in fixture["chapters"]:
        bind.execute(insert(chapters).values(**row).on_conflict_do_nothing())
    lessons = sa.table("review_lessons", sa.column("id", sa.String), sa.column("chapter_id", sa.String), sa.column("content", sa.JSON))
    for row in fixture["lessons"]:
        bind.execute(insert(lessons).values(**row).on_conflict_do_nothing())
    for row in fixture["lesson_grades"]:
        bind.execute(insert(lesson_grades).values(**row).on_conflict_do_nothing())


def downgrade():
    for table in ("material_completions", "lesson_materials", "teacher_resources", "teacher_class_students", "teacher_classes"):
        op.drop_table(table)
    op.drop_index("ix_review_lesson_grades_grade_id", table_name="review_lesson_grades")
    op.drop_table("review_lesson_grades")
    op.drop_table("review_grades")
