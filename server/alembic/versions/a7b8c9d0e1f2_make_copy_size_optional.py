"""make copy inventory size optional.

Revision ID: a7b8c9d0e1f2
Revises: 9c4e2a7f1b30
Create Date: 2026-08-12 12:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "9c4e2a7f1b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "run_copies",
        "total_size_bytes",
        existing_type=sa.BigInteger(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE run_copies SET total_size_bytes = 0 WHERE total_size_bytes IS NULL")
    op.alter_column(
        "run_copies",
        "total_size_bytes",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
