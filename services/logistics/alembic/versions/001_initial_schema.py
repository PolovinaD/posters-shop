"""Initial schema for logistics service

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

Creates:
- shipments table
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "logistics_schema"


def upgrade() -> None:
    # Create schema if not exists
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    
    # Create shipments table
    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="preparing"),
        sa.Column("tracking", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        schema=SCHEMA,
    )
    
    op.create_index("ix_shipments_order_id", "shipments", ["order_id"], schema=SCHEMA)
    op.create_index("ix_shipments_status", "shipments", ["status"], schema=SCHEMA)
    op.create_index("ix_shipments_tracking", "shipments", ["tracking"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_shipments_tracking", table_name="shipments", schema=SCHEMA)
    op.drop_index("ix_shipments_status", table_name="shipments", schema=SCHEMA)
    op.drop_index("ix_shipments_order_id", table_name="shipments", schema=SCHEMA)
    op.drop_table("shipments", schema=SCHEMA)
