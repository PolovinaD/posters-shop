"""Add escrow payment columns to orders

Revision ID: 003
Revises: 002
Create Date: 2026-09-16 00:00:00.000000

Adds:
- orders.payment_method ('stripe' | 'escrow'), NOT NULL with server default
  'stripe' so every pre-existing row stays a card order
- orders.customer_wallet, courier_wallet, escrow_contract_address,
  escrow_deploy_tx, escrow_amount_wei, escrow_status -- nullable because only
  escrow orders fill them
- index ix_orders_escrow_status (the reconciler polls open escrow rows)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "orders_schema"


def upgrade() -> None:
    op.add_column("orders", sa.Column("payment_method", sa.String(), nullable=False, server_default="stripe"), schema=SCHEMA)
    op.add_column("orders", sa.Column("customer_wallet", sa.String(42), nullable=True), schema=SCHEMA)
    op.add_column("orders", sa.Column("courier_wallet", sa.String(42), nullable=True), schema=SCHEMA)
    op.add_column("orders", sa.Column("escrow_contract_address", sa.String(42), nullable=True), schema=SCHEMA)
    op.add_column("orders", sa.Column("escrow_deploy_tx", sa.String(66), nullable=True), schema=SCHEMA)
    op.add_column("orders", sa.Column("escrow_amount_wei", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("orders", sa.Column("escrow_status", sa.String(), nullable=True), schema=SCHEMA)
    op.create_index("ix_orders_escrow_status", "orders", ["escrow_status"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_orders_escrow_status", table_name="orders", schema=SCHEMA)
    op.drop_column("orders", "escrow_status", schema=SCHEMA)
    op.drop_column("orders", "escrow_amount_wei", schema=SCHEMA)
    op.drop_column("orders", "escrow_deploy_tx", schema=SCHEMA)
    op.drop_column("orders", "escrow_contract_address", schema=SCHEMA)
    op.drop_column("orders", "courier_wallet", schema=SCHEMA)
    op.drop_column("orders", "customer_wallet", schema=SCHEMA)
    op.drop_column("orders", "payment_method", schema=SCHEMA)
