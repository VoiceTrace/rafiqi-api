"""Epic D — study_sessions, questions, attempts, mastery_records

Revision ID: d1e2f3a4b5c6
Revises: d4e6a2c9f1b7
Create Date: 2026-09-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "d4e6a2c9f1b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # study_sessions
    op.create_table(
        "study_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("current_stage", sa.String(length=20), nullable=False, server_default="setup"),
        sa.Column("current_concept_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("concepts_order", sa.JSON(), nullable=True),
        sa.Column("summary_card", sa.JSON(), nullable=True),
        sa.Column("gap_seed_ids", sa.JSON(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_study_sessions_school_id", "study_sessions", ["school_id"])
    op.create_index("ix_study_sessions_student_id", "study_sessions", ["student_id"])
    op.create_index("ix_study_sessions_lesson_id", "study_sessions", ["lesson_id"])

    # questions
    op.create_table(
        "questions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("concept_ref", sa.String(length=200), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("internal_answer_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["study_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_questions_school_id", "questions", ["school_id"])
    op.create_index("ix_questions_session_id", "questions", ["session_id"])
    op.create_index("ix_questions_student_id", "questions", ["student_id"])

    # attempts
    op.create_table(
        "attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("student_response", sa.Text(), nullable=False),
        sa.Column("correctness_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("error_type", sa.String(length=50), nullable=True),
        sa.Column("hint_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attempts_school_id", "attempts", ["school_id"])
    op.create_index("ix_attempts_question_id", "attempts", ["question_id"])
    op.create_index("ix_attempts_student_id", "attempts", ["student_id"])

    # mastery_records
    op.create_table(
        "mastery_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("lesson_id", sa.String(length=100), nullable=False),
        sa.Column("concept_ref", sa.String(length=200), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mastery_level", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("dominant_error_type", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False, server_default="forming"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "school_id", "student_id", "lesson_id", "concept_ref",
            name="uq_mastery_student_lesson_concept",
        ),
    )
    op.create_index("ix_mastery_records_school_id", "mastery_records", ["school_id"])
    op.create_index("ix_mastery_records_student_id", "mastery_records", ["student_id"])


def downgrade() -> None:
    op.drop_table("mastery_records")
    op.drop_table("attempts")
    op.drop_table("questions")
    op.drop_table("study_sessions")
