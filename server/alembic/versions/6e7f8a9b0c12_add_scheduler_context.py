"""add scheduler context and output path.

Revision ID: 6e7f8a9b0c12
Revises: 5d6f7a8b9c01
Create Date: 2026-08-05 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6e7f8a9b0c12"
down_revision: str | None = "5d6f7a8b9c01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("scheduler_system", sa.String(30), nullable=True))
    op.add_column(
        "runs",
        sa.Column(
            "scheduler_details",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column("runs", sa.Column("output_path", sa.String(2000), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "output_path")
    op.drop_column("runs", "scheduler_details")
    op.drop_column("runs", "scheduler_system")
