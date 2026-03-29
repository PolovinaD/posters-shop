"""Add refresh_tokens table

Revision ID: 002_add_refresh_tokens
Revises: 001
Create Date: 2026-03-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "002_add_refresh_tokens"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "users_schema"


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], [f"{SCHEMA}.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        schema=SCHEMA,
    )
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], schema=SCHEMA)
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens", schema=SCHEMA)
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens", schema=SCHEMA)
    op.drop_table("refresh_tokens", schema=SCHEMA)
