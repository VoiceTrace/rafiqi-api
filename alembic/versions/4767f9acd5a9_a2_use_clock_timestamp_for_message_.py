"""A2: use clock_timestamp for message created_at to avoid same-transaction ties

Revision ID: 4767f9acd5a9
Revises: 20a463a3c92c
Create Date: 2026-09-30 21:49:23.120625

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4767f9acd5a9'
down_revision: Union[str, Sequence[str], None] = '20a463a3c92c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Autogenerate can't diff server_default SQL expressions, so this is
    # hand-written. now()/CURRENT_TIMESTAMP is frozen for the whole
    # transaction in Postgres — a student message and Rafiqi's reply,
    # inserted in the same transaction, got identical created_at values,
    # making "most recent message" ordering non-deterministic on ties.
    # clock_timestamp() evaluates per-statement instead.
    op.alter_column(
        'conversation_messages', 'created_at',
        server_default=sa.text('clock_timestamp()'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'conversation_messages', 'created_at',
        server_default=sa.text('now()'),
    )
