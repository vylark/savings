"""Add notes column to reconciliation_event table.

Revision ID: 0004_add_recon_notes
Revises: 0003_physical_accounts_ledger
Create Date: 2026-10-12 08:57:43.531725

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_add_recon_notes"
down_revision: str | None = "0003_physical_accounts_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrades the database schema by adding notes column to reconciliation_event."""
    op.add_column("reconciliation_event", sa.Column("notes", sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrades the database schema by removing notes column from reconciliation_event."""
    op.drop_column("reconciliation_event", "notes")
