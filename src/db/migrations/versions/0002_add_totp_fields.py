"""Add TOTP 2FA fields to user database table.

Revision ID: 0002_add_totp_fields
Revises: 0001_create_user_table
Create Date: 2026-07-26 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0002_add_totp_fields"
down_revision: str | None = "0001_create_user_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Applies database schema changes adding totp_secret and is_totp_enabled columns."""
    op.add_column("user", sa.Column("totp_secret", sa.String(length=255), nullable=True))
    op.add_column(
        "user",
        sa.Column("is_totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    """Reverts database schema changes removing totp_secret and is_totp_enabled columns."""
    op.drop_column("user", "is_totp_enabled")
    op.drop_column("user", "totp_secret")
