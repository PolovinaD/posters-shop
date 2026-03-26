"""Initial schema for production service

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Schema for this service
SCHEMA = "production_schema"


def upgrade() -> None:
    # Create jobs table
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("items_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
        schema=SCHEMA,
    )
    
    # Create indexes
    op.create_index("ix_jobs_order_id", "jobs", ["order_id"], schema=SCHEMA)
    op.create_index("ix_jobs_status", "jobs", ["status"], schema=SCHEMA)


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_jobs_status", table_name="jobs", schema=SCHEMA)
    op.drop_index("ix_jobs_order_id", table_name="jobs", schema=SCHEMA)
    
    # Drop table
    op.drop_table("jobs", schema=SCHEMA)
