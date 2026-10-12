"""Add updated_at column to physical_account_share table.

Revision ID: 0005_add_updated_at_share
Revises: 0004_add_recon_notes
Create Date: 2026-10-12 11:06:56.568718

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_add_updated_at_share"
down_revision: str | None = "0004_add_recon_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrades the database schema by adding updated_at column to physical_account_share."""
    op.add_column(
        "physical_account_share",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    """Downgrades the database schema by removing updated_at column from physical_account_share."""
    op.drop_column("physical_account_share", "updated_at")

