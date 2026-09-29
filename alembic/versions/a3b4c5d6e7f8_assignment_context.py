"""Store assignment subject and chapter context.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("homework_assignments", sa.Column("subject", sa.String(length=255), nullable=False, server_default="Uncategorized"))
    op.add_column("homework_assignments", sa.Column("chapter", sa.String(length=255), nullable=False, server_default="Uncategorized"))
    op.create_index("ix_homework_assignments_subject", "homework_assignments", ["subject"])
    op.create_index("ix_homework_assignments_chapter", "homework_assignments", ["chapter"])
    op.alter_column("homework_assignments", "subject", server_default=None)
    op.alter_column("homework_assignments", "chapter", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_homework_assignments_chapter", table_name="homework_assignments")
    op.drop_index("ix_homework_assignments_subject", table_name="homework_assignments")
    op.drop_column("homework_assignments", "chapter")
    op.drop_column("homework_assignments", "subject")
