"""Add shipping address columns to orders

Revision ID: 002
Revises: 001
Create Date: 2026-09-12 00:00:00.000000

Adds:
- orders.shipping_recipient_name, shipping_street, shipping_city,
  shipping_postal_code, shipping_country, shipping_phone

All six are nullable: orders created before this revision have no address,
and the migration must not fail on them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "orders_schema"


def upgrade() -> None:
    op.add_column("orders", sa.Column("shipping_recipient_name", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("orders", sa.Column("shipping_street", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("orders", sa.Column("shipping_city", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("orders", sa.Column("shipping_postal_code", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("orders", sa.Column("shipping_country", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("orders", sa.Column("shipping_phone", sa.String(), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("orders", "shipping_phone", schema=SCHEMA)
    op.drop_column("orders", "shipping_country", schema=SCHEMA)
    op.drop_column("orders", "shipping_postal_code", schema=SCHEMA)
    op.drop_column("orders", "shipping_city", schema=SCHEMA)
    op.drop_column("orders", "shipping_street", schema=SCHEMA)
    op.drop_column("orders", "shipping_recipient_name", schema=SCHEMA)
