"""Initial schema for orders service

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

Creates:
- orders table
- order_items table
- outbox_events table
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "orders_schema"


def upgrade() -> None:
    # Create schema if not exists
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    
    # Create orders table
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_email", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="created"),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("checkout_session_id", sa.String(), nullable=True),
        sa.Column("payment_intent_id", sa.String(), nullable=True),
        schema=SCHEMA,
    )
    
    op.create_index("ix_orders_customer_email", "orders", ["customer_email"], schema=SCHEMA)
    op.create_index("ix_orders_status", "orders", ["status"], schema=SCHEMA)
    
    # Create order_items table
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.orders.id"), nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        schema=SCHEMA,
    )
    
    # Create outbox_events table
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", sa.String(100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    
    op.create_index("ix_outbox_pending", "outbox_events", ["delivered_at", "retry_after"], schema=SCHEMA)
    op.create_index("ix_outbox_event_type", "outbox_events", ["event_type"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("outbox_events", schema=SCHEMA)
    op.drop_table("order_items", schema=SCHEMA)
    op.drop_table("orders", schema=SCHEMA)
