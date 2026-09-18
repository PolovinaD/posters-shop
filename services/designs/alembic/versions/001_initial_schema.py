"""Initial schema for designs service

Revision ID: 001
Revises:
Create Date: 2026-09-18 00:00:00.000000

Creates:
- generations table (one prompt -> one async image job; status queued/generating/ready/failed)
- saved_prompts table (prompts the customer keeps for reuse)
- style_profiles table (per-customer style summary, refreshed lazily)
- purchases table (one row per order item from ORDER_PAID, feeds the style profile)
- processed_events table (durable consumer-side idempotency for outbox events)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "designs_schema"


def upgrade() -> None:
    # Create schema if not exists
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Create generations table
    op.create_table(
        "generations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_email", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("effective_prompt", sa.Text(), nullable=False),
        sa.Column("personalise", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("image_key", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("catalog_product_sku", sa.String(), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_generations_customer_created", "generations", ["customer_email", "created_at"], schema=SCHEMA
    )
    op.create_index(
        "ix_generations_status_retry", "generations", ["status", "retry_after"], schema=SCHEMA
    )

    # Create saved_prompts table
    op.create_table(
        "saved_prompts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_email", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_saved_prompts_customer", "saved_prompts", ["customer_email"], schema=SCHEMA)

    # Create style_profiles table
    op.create_table(
        "style_profiles",
        sa.Column("customer_email", sa.String(), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("prompt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("purchase_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )

    # Create purchases table
    op.create_table(
        "purchases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_email", sa.String(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("order_id", "sku", name="uq_purchases_order_sku"),
        schema=SCHEMA,
    )
    op.create_index("ix_purchases_customer", "purchases", ["customer_email"], schema=SCHEMA)

    # Create processed_events table
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("processed_events", schema=SCHEMA)
    op.drop_table("purchases", schema=SCHEMA)
    op.drop_table("style_profiles", schema=SCHEMA)
    op.drop_table("saved_prompts", schema=SCHEMA)
    op.drop_table("generations", schema=SCHEMA)
