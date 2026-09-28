"""Add teacher class groups and student enrollments.

Revision ID: 94c7d2a1b0e8
Revises: 83bcb2215849
Create Date: 2026-09-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "94c7d2a1b0e8"
down_revision: Union[str, Sequence[str], None] = "83bcb2215849"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "class_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("grade_level", sa.String(length=100), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=False),
        sa.Column("academic_year", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["review_subjects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "school_id", "teacher_id", "name", "academic_year",
            name="uq_class_group_teacher_name_year",
        ),
    )
    op.create_index(op.f("ix_class_groups_school_id"), "class_groups", ["school_id"])
    op.create_index(op.f("ix_class_groups_teacher_id"), "class_groups", ["teacher_id"])
    op.create_index(op.f("ix_class_groups_subject_id"), "class_groups", ["subject_id"])

    op.create_table(
        "class_enrollments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("class_group_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_group_id"], ["class_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("class_group_id", "student_id", name="uq_class_enrollment_student"),
    )
    op.create_index(op.f("ix_class_enrollments_school_id"), "class_enrollments", ["school_id"])
    op.create_index(op.f("ix_class_enrollments_class_group_id"), "class_enrollments", ["class_group_id"])
    op.create_index(op.f("ix_class_enrollments_student_id"), "class_enrollments", ["student_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_class_enrollments_student_id"), table_name="class_enrollments")
    op.drop_index(op.f("ix_class_enrollments_class_group_id"), table_name="class_enrollments")
    op.drop_index(op.f("ix_class_enrollments_school_id"), table_name="class_enrollments")
    op.drop_table("class_enrollments")
    op.drop_index(op.f("ix_class_groups_subject_id"), table_name="class_groups")
    op.drop_index(op.f("ix_class_groups_teacher_id"), table_name="class_groups")
    op.drop_index(op.f("ix_class_groups_school_id"), table_name="class_groups")
    op.drop_table("class_groups")
