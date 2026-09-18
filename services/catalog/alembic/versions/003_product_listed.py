"""products.listed — custom AI motifs are unlisted (D-13)

Revision ID: 003
Revises: 002
Create Date: 2026-09-18 00:00:00.000000

The AI poster studio's "Print this" turns a customer's design into a catalog
family so it can ride the existing cart, checkout and production pipeline.
Those families are personal: they must be reachable by direct SKU (the studio's
"View product" link, the cart, `/internal/resolve-prices`) but must not appear
in the public grid or the category tabs. `listed` carries exactly that
distinction; every existing row is listed, so the default is true.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "catalog_schema"


def upgrade() -> None:
    op.add_column("products", sa.Column("listed", sa.Boolean(), nullable=False, server_default=sa.true()), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("products", "listed", schema=SCHEMA)
