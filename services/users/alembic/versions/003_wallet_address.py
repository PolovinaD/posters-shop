"""Add users.wallet_address (courier Ethereum wallet, ESC-04)

Revision ID: 003_wallet_address
Revises: 002_add_refresh_tokens
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "003_wallet_address"
down_revision: Union[str, None] = "002_add_refresh_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "users_schema"


def upgrade() -> None:
    op.add_column("users", sa.Column("wallet_address", sa.String(42), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("users", "wallet_address", schema=SCHEMA)
