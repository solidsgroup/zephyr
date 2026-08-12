from __future__ import annotations

import json
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ArtifactObject, Run, RunArtifact, RunCopy, RunMetadata, RunSearch


def searchable(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def run_fields(run: Run) -> list[Any]:
    return [
        run.id,
        run.alamo_hash,
        run.name,
        run.host,
        run.platform,
        run.scheduler_job_id,
        run.scheduler_system,
        run.scheduler_details,
        run.output_path,
        run.git_commit,
        run.git_repository_url,
        run.command,
        run.tags,
        run.notes,
    ]


async def refresh_run_search_documents(
    db: AsyncSession,
    run_ids: set[uuid.UUID],
) -> None:
    """Rebuild denormalized search records with a bounded number of queries."""
    if not run_ids:
        return
    runs = list(await db.scalars(select(Run).where(Run.id.in_(run_ids))))
    metadata_rows = (
        await db.execute(
            select(RunMetadata.run_id, RunMetadata.raw_text).where(RunMetadata.run_id.in_(run_ids))
        )
    ).all()
    copy_rows = (
        await db.execute(
            select(
                RunCopy.run_id,
                RunCopy.site,
                RunCopy.host,
                RunCopy.path,
                RunCopy.platform,
                RunCopy.last_action,
            ).where(RunCopy.run_id.in_(run_ids))
        )
    ).all()
    artifact_rows = (
        await db.execute(
            select(
                RunArtifact.run_id,
                RunArtifact.logical_name,
                RunArtifact.path,
                RunArtifact.kind,
                RunArtifact.attributes,
                RunArtifact.derivation,
                RunArtifact.object_sha256,
                ArtifactObject.content_type,
            )
            .join(ArtifactObject, ArtifactObject.sha256 == RunArtifact.object_sha256)
            .where(RunArtifact.run_id.in_(run_ids))
        )
    ).all()
    existing = {
        record.run_id: record
        for record in await db.scalars(select(RunSearch).where(RunSearch.run_id.in_(run_ids)))
    }

    parts: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for run_id, raw_text in metadata_rows:
        parts[run_id].append(raw_text)
    for row in copy_rows:
        parts[row[0]].extend(row[1:])
    for row in artifact_rows:
        parts[row[0]].extend(row[1:])

    for run in runs:
        document = "\n".join(
            text for value in [*run_fields(run), *parts[run.id]] if (text := searchable(value))
        )
        record = existing.get(run.id)
        if record is None:
            db.add(RunSearch(run_id=run.id, document=document))
        else:
            record.document = document


async def refresh_run_search_document(db: AsyncSession, run_id: uuid.UUID) -> None:
    await refresh_run_search_documents(db, {run_id})
