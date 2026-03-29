"""add line_item_updates to disputes

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-29 12:01:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("disputes", sa.Column("line_item_updates", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("disputes", "line_item_updates")
