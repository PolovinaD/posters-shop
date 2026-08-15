"""Initial schema for notifications service

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

Creates:
- processed_events table (durable consumer-side idempotency)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "notifications_schema"


def upgrade() -> None:
    # Create schema if not exists
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Create processed_events table
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("processed_events", schema=SCHEMA)
