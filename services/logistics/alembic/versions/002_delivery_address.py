"""Add delivery address columns to shipments

Revision ID: 002
Revises: 001
Create Date: 2026-09-12 00:00:00.000000

Adds:
- shipments.recipient_name, street, city, postal_code, country, recipient_phone

The delivery copy of the order's shipping address (event-carried state
transfer), written once at shipment creation. All six are nullable: shipments
created before this revision have none, and a shipment created while the orders
service is unreachable keeps them null.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "logistics_schema"


def upgrade() -> None:
    op.add_column("shipments", sa.Column("recipient_name", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("shipments", sa.Column("street", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("shipments", sa.Column("city", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("shipments", sa.Column("postal_code", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("shipments", sa.Column("country", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("shipments", sa.Column("recipient_phone", sa.String(), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("shipments", "recipient_phone", schema=SCHEMA)
    op.drop_column("shipments", "country", schema=SCHEMA)
    op.drop_column("shipments", "postal_code", schema=SCHEMA)
    op.drop_column("shipments", "city", schema=SCHEMA)
    op.drop_column("shipments", "street", schema=SCHEMA)
    op.drop_column("shipments", "recipient_name", schema=SCHEMA)
