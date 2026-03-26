"""Initial schema for inventory service

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

Creates:
- stock table
- reservations table
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "inventory_schema"


def upgrade() -> None:
    # Create schema if not exists
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    
    # Create stock table
    op.create_table(
        "stock",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        schema=SCHEMA,
    )
    
    op.create_index("ix_stock_sku", "stock", ["sku"], unique=True, schema=SCHEMA)
    
    # Create reservations table
    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    
    op.create_index("ix_reservations_expires_at", "reservations", ["expires_at"], schema=SCHEMA)
    op.create_index("ix_reservations_order_id", "reservations", ["order_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("reservations", schema=SCHEMA)
    op.drop_table("stock", schema=SCHEMA)
