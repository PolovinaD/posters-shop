"""Initial schema for catalog service

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

SCHEMA = "catalog_schema"


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("category", sa.String(), nullable=False, server_default="General"),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("sizes", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true"),
        schema=SCHEMA,
    )
    op.create_index("ix_products_sku", "products", ["sku"], unique=True, schema=SCHEMA)

    op.create_table(
        "sizes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("price_delta", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint("name", name="uq_sizes_name"),
        schema=SCHEMA,
    )

    op.create_table(
        "frame_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("extra_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint("name", name="uq_frame_options_name"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("frame_options", schema=SCHEMA)
    op.drop_table("sizes", schema=SCHEMA)
    op.drop_index("ix_products_sku", table_name="products", schema=SCHEMA)
    op.drop_table("products", schema=SCHEMA)
