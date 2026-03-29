"""add partial unique index for one active policy per member

Revision ID: a1b2c3d4e5f6
Revises: f40fa31b803c
Create Date: 2026-03-29 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f40fa31b803c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_policies_member_id_active",
        "policies",
        ["member_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_policies_member_id_active", table_name="policies")
