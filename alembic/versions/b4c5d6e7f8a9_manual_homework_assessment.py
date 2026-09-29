"""Add grade-scoped manual homework assessment workflow.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("grade_level", sa.String(length=100), nullable=True))
    op.create_index("ix_users_grade_level", "users", ["grade_level"])
    op.add_column("homework_assignments", sa.Column("grade_level", sa.String(length=100), nullable=False, server_default="Unassigned"))
    op.create_index("ix_homework_assignments_grade_level", "homework_assignments", ["grade_level"])
    op.alter_column("homework_assignments", "grade_level", server_default=None)
    op.alter_column("homework_questions", "correct_answer", existing_type=sa.String(length=10), nullable=True)
    op.alter_column("homework_attempts", "student_answer", existing_type=sa.String(length=10), type_=sa.Text())
    op.add_column("homework_attempts", sa.Column("teacher_score", sa.Float(), nullable=True))
    op.add_column("homework_attempts", sa.Column("teacher_comment", sa.Text(), nullable=True))
    op.add_column("student_assignments", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "homework_hint_reveals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hint_index", sa.Integer(), nullable=False),
        sa.Column("revealed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_assignment_id"], ["student_assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["homework_questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_assignment_id", "question_id", "hint_index", name="uq_homework_hint_reveal"),
    )
    op.create_index("ix_homework_hint_reveals_school_id", "homework_hint_reveals", ["school_id"])
    op.create_index("ix_homework_hint_reveals_student_assignment_id", "homework_hint_reveals", ["student_assignment_id"])
    op.create_index("ix_homework_hint_reveals_question_id", "homework_hint_reveals", ["question_id"])


def downgrade() -> None:
    op.drop_index("ix_homework_hint_reveals_question_id", table_name="homework_hint_reveals")
    op.drop_index("ix_homework_hint_reveals_student_assignment_id", table_name="homework_hint_reveals")
    op.drop_index("ix_homework_hint_reveals_school_id", table_name="homework_hint_reveals")
    op.drop_table("homework_hint_reveals")
    op.drop_column("student_assignments", "approved_at")
    op.drop_column("homework_attempts", "teacher_comment")
    op.drop_column("homework_attempts", "teacher_score")
    op.alter_column("homework_attempts", "student_answer", existing_type=sa.Text(), type_=sa.String(length=10))
    op.alter_column("homework_questions", "correct_answer", existing_type=sa.String(length=10), nullable=False)
    op.drop_index("ix_homework_assignments_grade_level", table_name="homework_assignments")
    op.drop_column("homework_assignments", "grade_level")
    op.drop_index("ix_users_grade_level", table_name="users")
    op.drop_column("users", "grade_level")
