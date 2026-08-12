"""add project folders and run placements.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-08-12 14:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: str | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_folders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["project_folders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_folders_project_parent",
        "project_folders",
        ["project_id", "parent_id"],
        unique=False,
    )
    op.add_column("run_projects", sa.Column("folder_id", sa.Uuid(), nullable=True))
    op.add_column(
        "run_projects",
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_foreign_key(
        "fk_run_projects_folder_id",
        "run_projects",
        "project_folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_run_projects_folder_id",
        "run_projects",
        ["folder_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_run_projects_folder_id", table_name="run_projects")
    op.drop_constraint("fk_run_projects_folder_id", "run_projects", type_="foreignkey")
    op.drop_column("run_projects", "position")
    op.drop_column("run_projects", "folder_id")
    op.drop_index("ix_project_folders_project_parent", table_name="project_folders")
    op.drop_table("project_folders")
