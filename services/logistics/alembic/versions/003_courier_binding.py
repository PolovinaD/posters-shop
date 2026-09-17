"""Record who bound the courier wallet on a shipment

Revision ID: 003
Revises: 002
Create Date: 2026-09-17 00:00:00.000000

Adds:
- shipments.courier_id       JWT `sub` of the person who picked the parcel up
                             (the user's email); NULL when the auto-advance worker
                             bound LOGISTICS_DEFAULT_COURIER_WALLET
- shipments.courier_wallet   the wallet actually sent to orders (CONTRACT B)
- shipments.courier_bound_at when that happened

All three nullable: rows picked up before this revision have none, and a pick-up
that binds no wallet (neither explicit nor default) keeps them null. Written only
on the dispatched -> in_transit transition that binds a wallet.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "logistics_schema"


def upgrade() -> None:
    op.add_column("shipments", sa.Column("courier_id", sa.String(), nullable=True), schema=SCHEMA)
    op.add_column("shipments", sa.Column("courier_wallet", sa.String(42), nullable=True), schema=SCHEMA)
    op.add_column("shipments", sa.Column("courier_bound_at", sa.DateTime(), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("shipments", "courier_bound_at", schema=SCHEMA)
    op.drop_column("shipments", "courier_wallet", schema=SCHEMA)
    op.drop_column("shipments", "courier_id", schema=SCHEMA)
