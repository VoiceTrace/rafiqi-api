"""A-USER: add avatar_url to users

Revision ID: c3d5f1a8b290
Revises: b2c4f1a8e390
Create Date: 2026-09-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d5f1a8b290"
down_revision: Union[str, None] = "b2c4f1a8e390"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
