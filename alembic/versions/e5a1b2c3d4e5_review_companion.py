"""Permanent bilingual lesson review companion.

Revision ID: e5a1b2c3d4e5
Revises: d4e6a2c9f1b7
"""
import json
from pathlib import Path
from alembic import op
import sqlalchemy as sa

revision = "e5a1b2c3d4e5"
down_revision = "d4e6a2c9f1b7"
branch_labels = None
depends_on = None


def upgrade():
    lessons = op.create_table("review_lessons",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("content", sa.JSON(), nullable=False))
    op.create_table("review_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.String(100), sa.ForeignKey("review_lessons.id"), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("school_id", "student_id", "lesson_id", name="uq_review_student_lesson"))
    # Immutable migration fixture; no dependency on later service code.
    content = json.loads((Path(__file__).parent / "fixtures" / "review-newton-v1.json").read_text(encoding="utf-8"))
    op.bulk_insert(lessons, [{"id": "newton-third-law", "content": content}])


def downgrade():
    op.drop_table("review_sessions")
    op.drop_table("review_lessons")
