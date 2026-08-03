"""add run synchronization digests.

Revision ID: 5d6f7a8b9c01
Revises: 7a1d6e4c2b90
Create Date: 2026-08-03 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5d6f7a8b9c01"
down_revision: str | None = "7a1d6e4c2b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("run_outputs", sa.Column("stdout_digest", sa.String(64), nullable=True))
    op.add_column("run_outputs", sa.Column("git_diff_digest", sa.String(64), nullable=True))
    op.add_column("run_outputs", sa.Column("thermo_digest", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("run_outputs", "thermo_digest")
    op.drop_column("run_outputs", "git_diff_digest")
    op.drop_column("run_outputs", "stdout_digest")
