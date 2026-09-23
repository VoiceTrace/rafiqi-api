"""Persist concept-scoped review attempts with assessment taxonomy.

Revision ID: a7c3d4e5f6a7
Revises: f6b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c3d4e5f6a7"
down_revision = "f6b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "review_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("school_id", sa.Uuid(), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("review_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_id", sa.String(100), sa.ForeignKey("review_lessons.id"), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.String(100), nullable=False),
        sa.Column("concept_ref", sa.String(100), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("option_id", sa.String(100), nullable=True),
        sa.Column("correctness_score", sa.Float(), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("hint_level", sa.Integer(), nullable=False),
        sa.Column("assisted", sa.Boolean(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "request_id", name="uq_review_attempt_session_request"),
        sa.CheckConstraint("correctness_score >= 0 AND correctness_score <= 1", name="ck_review_attempt_score"),
        sa.CheckConstraint("hint_level >= 0", name="ck_review_attempt_hint_level"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_review_attempt_number"),
        sa.CheckConstraint(
            "error_type IS NULL OR error_type IN ("
            "'force_pair_unequal_magnitude', 'force_pair_missing_reaction', "
            "'force_pair_incomplete_distinct_objects', 'force_pair_missing_distinct_objects', "
            "'balanced_force_means_stopped', 'kinetic_energy_requires_motion', "
            "'equivalent_fraction_denominator_only')",
            name="ck_review_attempt_error_type",
        ),
    )
    op.create_index("ix_review_attempts_school_id", "review_attempts", ["school_id"])
    op.create_index("ix_review_attempts_student_id", "review_attempts", ["student_id"])
    op.create_index("ix_review_attempts_session_id", "review_attempts", ["session_id"])


def downgrade():
    op.drop_index("ix_review_attempts_session_id", table_name="review_attempts")
    op.drop_index("ix_review_attempts_student_id", table_name="review_attempts")
    op.drop_index("ix_review_attempts_school_id", table_name="review_attempts")
    op.drop_table("review_attempts")
