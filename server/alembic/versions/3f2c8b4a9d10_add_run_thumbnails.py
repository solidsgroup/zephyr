"""add run thumbnails.

Revision ID: 3f2c8b4a9d10
Revises: 84b7c9d2e1f0
Create Date: 2026-08-03 14:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3f2c8b4a9d10"
down_revision: str | None = "84b7c9d2e1f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("thumbnail_artifact_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_runs_thumbnail_artifact",
        "runs",
        "run_artifacts",
        ["thumbnail_artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_runs_thumbnail_artifact", "runs", type_="foreignkey")
    op.drop_column("runs", "thumbnail_artifact_id")
