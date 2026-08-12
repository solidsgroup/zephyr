"""add run copy locations.

Revision ID: 9c4e2a7f1b30
Revises: 6e7f8a9b0c12
Create Date: 2026-08-12 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9c4e2a7f1b30"
down_revision: str | None = "6e7f8a9b0c12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_copies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("site", sa.String(255), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("path", sa.String(2000), nullable=False),
        sa.Column("platform", sa.String(255), nullable=True),
        sa.Column("file_count", sa.BigInteger(), nullable=False),
        sa.Column("total_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("has_cell_data", sa.Boolean(), nullable=False),
        sa.Column("has_node_data", sa.Boolean(), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("last_action", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "site", "path", name="uq_run_copy_location"),
    )
    op.create_index(
        "ix_run_copies_run_updated",
        "run_copies",
        ["run_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_copies_run_updated", table_name="run_copies")
    op.drop_table("run_copies")
