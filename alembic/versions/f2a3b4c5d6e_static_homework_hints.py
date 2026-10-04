"""Add teacher-authored static hints to homework questions.

Revision ID: f2a3b4c5d6e
Revises: e1f2a3b4c5d6
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

from alembic import op


revision: str = "f2a3b4c5d6e"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing questions are preserved with an empty legacy value. New question
    # validation and distribution rules require exactly three teacher-written hints.
    op.add_column(
        "homework_questions",
        sa.Column("hints", JSON, nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.alter_column("homework_questions", "hints", server_default=None)


def downgrade() -> None:
    op.drop_column("homework_questions", "hints")
