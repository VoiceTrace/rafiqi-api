"""A1: add schools, users, conversations, student_profiles, profile_traits

Revision ID: ef81a87bd4aa
Revises:
Create Date: 2026-09-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ef81a87bd4aa"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- schools (tenant root) ---
    op.create_table(
        "schools",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- users (teachers + students, single table) ---
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_school_id", "users", ["school_id"])

    # --- conversations (Cave chat sessions — populated by A2) ---
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_school_id", "conversations", ["school_id"])
    op.create_index("ix_conversations_student_id", "conversations", ["student_id"])

    # --- student_profiles (anchor record, one per student) ---
    op.create_table(
        "student_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id"),
    )
    op.create_index("ix_student_profiles_school_id", "student_profiles", ["school_id"])

    # --- profile_traits (core of A1: one row per trait per student) ---
    op.create_table(
        "profile_traits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("source_conversation_id", sa.UUID(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("trait_key", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("teaching_tip", sa.Text(), nullable=True),
        # score: agent-facing 0.0–1.0 confidence float
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
        # confidence: user-facing label ("confident" | "still_forming"), derived from score
        sa.Column(
            "confidence", sa.String(20), nullable=False, server_default="still_forming"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["student_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_profile_traits_school_id", "profile_traits", ["school_id"])
    op.create_index("ix_profile_traits_profile_id", "profile_traits", ["profile_id"])


def downgrade() -> None:
    op.drop_table("profile_traits")
    op.drop_table("student_profiles")
    op.drop_table("conversations")
    op.drop_table("users")
    op.drop_table("schools")
