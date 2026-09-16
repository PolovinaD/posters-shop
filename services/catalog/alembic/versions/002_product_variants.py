"""Variant model for catalog: products become families, variants are sellable

Revision ID: 002
Revises: 001
Create Date: 2026-09-16 00:00:00.000000

Before this revision the catalog priced options as independent additive
modifiers: a product had a base price, `sizes.price_delta` adjusted it per
format, and `frame_options.extra_price` added a flat surcharge. That model only
holds while options do not interact — and frame price does interact with size,
because an A1 frame needs roughly twice the moulding of an A4.

Inventory already used the variant model (`FRAME-BLACK-A1` is stocked separately
from `FRAME-BLACK-A3`, with its own quantity). This revision makes the catalog
agree with the warehouse: `products` becomes the family (one row per motif) and
every sellable unit is a variant row carrying its own SKU and its own price.

`products.sizes`, `sizes.price_delta` and `frame_options.extra_price` are dropped
because a variant's price now lives on the variant — keeping them would be two
sources of truth for the same number.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "catalog_schema"


def upgrade() -> None:
    op.create_table(
        "product_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("size", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.UniqueConstraint("product_id", "size", name="uq_product_variant_size"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_product_variants_sku", "product_variants", ["sku"], unique=True, schema=SCHEMA
    )

    op.create_table(
        "frame_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "frame_option_id",
            sa.Integer(),
            sa.ForeignKey(f"{SCHEMA}.frame_options.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("size", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.UniqueConstraint("frame_option_id", "size", name="uq_frame_variant_size"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_frame_variants_sku", "frame_variants", ["sku"], unique=True, schema=SCHEMA
    )

    # Ordering for the size picker: A4 is the smallest, A1 the largest.
    op.add_column(
        "sizes",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    # A SKU prefix per frame colour, so a frame variant's SKU is derivable and
    # lines up with the stock SKUs inventory already carries (FRAME-BLACK-A2).
    op.add_column(
        "frame_options",
        sa.Column("sku_prefix", sa.String(), nullable=False, server_default="FRAME"),
        schema=SCHEMA,
    )

    # Superseded: the variant carries the price now.
    op.drop_column("products", "sizes", schema=SCHEMA)
    op.drop_column("sizes", "price_delta", schema=SCHEMA)
    op.drop_column("frame_options", "extra_price", schema=SCHEMA)


def downgrade() -> None:
    op.add_column(
        "frame_options",
        sa.Column("extra_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.add_column(
        "sizes",
        sa.Column("price_delta", sa.Numeric(10, 2), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.add_column("products", sa.Column("sizes", sa.String(), nullable=True), schema=SCHEMA)

    op.drop_column("frame_options", "sku_prefix", schema=SCHEMA)
    op.drop_column("sizes", "sort_order", schema=SCHEMA)

    op.drop_index("ix_frame_variants_sku", table_name="frame_variants", schema=SCHEMA)
    op.drop_table("frame_variants", schema=SCHEMA)
    op.drop_index("ix_product_variants_sku", table_name="product_variants", schema=SCHEMA)
    op.drop_table("product_variants", schema=SCHEMA)
