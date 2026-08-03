"""add device authorizations.

Revision ID: 84b7c9d2e1f0
Revises: c16577073fa4
Create Date: 2026-08-03 13:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "84b7c9d2e1f0"
down_revision: str | None = "c16577073fa4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_authorizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_name", sa.String(length=100), nullable=False),
        sa.Column("device_secret_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_secret_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_device_authorizations_expires_at"),
        "device_authorizations",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_authorizations_user_id"),
        "device_authorizations",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_device_authorizations_user_id"), table_name="device_authorizations")
    op.drop_index(op.f("ix_device_authorizations_expires_at"), table_name="device_authorizations")
    op.drop_table("device_authorizations")
