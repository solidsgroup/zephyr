"""add captured run output and repository provenance.

Revision ID: 7a1d6e4c2b90
Revises: 3f2c8b4a9d10
Create Date: 2026-08-03 14:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7a1d6e4c2b90"
down_revision: str | None = "3f2c8b4a9d10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("git_repository_url", sa.String(length=500), nullable=True))
    op.create_table(
        "run_outputs",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stdout_truncated", sa.Boolean(), nullable=False),
        sa.Column("git_diff", sa.Text(), nullable=False),
        sa.Column("git_diff_truncated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )


def downgrade() -> None:
    op.drop_table("run_outputs")
    op.drop_column("runs", "git_repository_url")
