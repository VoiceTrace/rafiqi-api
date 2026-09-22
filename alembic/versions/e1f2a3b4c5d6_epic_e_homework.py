"""Epic E — homework_assignments, homework_questions, student_assignments, homework_attempts

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-09-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "homework_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("school_id", UUID(as_uuid=True), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("teacher_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("lesson_id", sa.String(255), nullable=False, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        # RAFIQI_V2: sa.Column("is_differentiated", sa.Boolean, nullable=False, server_default="false"),
        # PARENT_V2: sa.Column("parent_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "homework_questions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("school_id", UUID(as_uuid=True), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("assignment_id", UUID(as_uuid=True), sa.ForeignKey("homework_assignments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("concept_ref", sa.String(255), nullable=True),
        sa.Column("question_text", sa.Text, nullable=False),
        sa.Column("format", sa.String(20), nullable=False, server_default="mcq"),
        sa.Column("options", JSON, nullable=False),
        sa.Column("correct_answer", sa.String(10), nullable=False),
        sa.Column("order", sa.Integer, nullable=False, server_default="0"),
        # RAFIQI_V2: sa.Column("hint_1", sa.Text, nullable=True),
        # RAFIQI_V2: sa.Column("hint_2", sa.Text, nullable=True),
    )

    op.create_table(
        "student_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("school_id", UUID(as_uuid=True), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("student_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("assignment_id", UUID(as_uuid=True), sa.ForeignKey("homework_assignments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="assigned"),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # PARENT_V2: sa.Column("parent_delivery_status", sa.String(20), nullable=True),
        # PARENT_V2: sa.Column("parent_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("school_id", "student_id", "assignment_id", name="uq_student_assignment"),
    )

    op.create_table(
        "homework_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("school_id", UUID(as_uuid=True), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("student_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("student_assignment_id", UUID(as_uuid=True), sa.ForeignKey("student_assignments.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("question_id", UUID(as_uuid=True), sa.ForeignKey("homework_questions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("student_answer", sa.String(10), nullable=False),
        sa.Column("is_correct", sa.Boolean, nullable=False),
        sa.Column("correctness_score", sa.Float, nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("school_id", "student_id", "question_id", name="uq_homework_attempt"),
    )


def downgrade() -> None:
    op.drop_table("homework_attempts")
    op.drop_table("student_assignments")
    op.drop_table("homework_questions")
    op.drop_table("homework_assignments")
