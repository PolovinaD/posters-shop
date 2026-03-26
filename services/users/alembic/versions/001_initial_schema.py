"""Initial schema for users service

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

Creates:
- users table
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "users_schema"


def upgrade() -> None:
    # Create schema if not exists
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    
    # Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="customer"),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("last_name", sa.String(), nullable=True),
        schema=SCHEMA,
    )
    
    op.create_index("ix_users_id", "users", ["id"], schema=SCHEMA)
    op.create_index("ix_users_email", "users", ["email"], unique=True, schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users", schema=SCHEMA)
    op.drop_index("ix_users_id", table_name="users", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
