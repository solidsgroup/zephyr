"""add indexed run search documents.

Revision ID: d9e0f1a2b3c4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-12 14:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_search",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("document", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute(
            sa.text(
                """
                INSERT INTO run_search (run_id, document)
                SELECT r.id, concat_ws(E'\\n',
                    r.id::text, r.alamo_hash, r.name, r.host, r.platform,
                    r.scheduler_job_id, r.scheduler_system, r.scheduler_details::text,
                    r.output_path, r.git_commit, r.git_repository_url, r.command::text,
                    r.tags::text, r.notes,
                    (SELECT m.raw_text FROM run_metadata m WHERE m.run_id = r.id),
                    (SELECT string_agg(concat_ws(' ', c.site, c.host, c.path, c.platform,
                                                c.last_action), E'\\n')
                       FROM run_copies c WHERE c.run_id = r.id),
                    (SELECT string_agg(concat_ws(' ', a.logical_name, a.path, a.kind,
                                                a.attributes::text, a.derivation::text,
                                                a.object_sha256, o.content_type), E'\\n')
                       FROM run_artifacts a
                       JOIN artifact_objects o ON o.sha256 = a.object_sha256
                      WHERE a.run_id = r.id)
                )
                FROM runs r
                """
            )
        )
        op.execute(
            "CREATE INDEX ix_run_search_document_trgm "
            "ON run_search USING gin (document gin_trgm_ops)"
        )
    else:
        op.execute(
            "INSERT INTO run_search (run_id, document) "
            "SELECT id, COALESCE(name, '') || ' ' || COALESCE(alamo_hash, '') FROM runs"
        )


def downgrade() -> None:
    op.drop_table("run_search")
