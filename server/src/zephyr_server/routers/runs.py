from __future__ import annotations

import hashlib
import posixpath
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..dependencies import current_user
from ..metadata import parse_metadata, slurm_context_from_metadata, status_from_metadata
from ..models import (
    Project,
    ProjectMembership,
    Run,
    RunArtifact,
    RunMetadata,
    RunOutput,
    RunProject,
    ThermoPoint,
    ThermoSeries,
    User,
    ensure_utc,
    utcnow,
)
from ..schemas import (
    ArtifactPreview,
    Heartbeat,
    MetadataRead,
    MetadataWrite,
    RunCreate,
    RunOutputRead,
    RunOutputWrite,
    RunRead,
    RunSyncState,
    RunSyncStateRequest,
    RunUpdate,
    ThermoBatch,
    ThermoRow,
    ThermoSeriesRead,
)

router = APIRouter(prefix="/runs", tags=["runs"])


def effective_status(run: Run) -> str:
    if run.status in {"starting", "running"} and run.last_heartbeat:
        if utcnow() - ensure_utc(run.last_heartbeat) > timedelta(minutes=2):
            return "unreachable"
    return run.status


def alamo_output_path(scheduler_details: dict[str, str]) -> str | None:
    plot_file = scheduler_details.get("plot_file")
    if not plot_file:
        return None
    if plot_file.startswith("/"):
        return posixpath.normpath(plot_file)
    submit_directory = scheduler_details.get("submit_directory")
    if not submit_directory:
        return None
    return posixpath.normpath(posixpath.join(submit_directory, plot_file))


def run_read(
    run: Run,
    artifact_count: int = 0,
    artifact_previews: list[ArtifactPreview] | None = None,
    metadata_values: dict[str, str] | None = None,
) -> RunRead:
    data = {column.name: getattr(run, column.name) for column in Run.__table__.columns}
    metadata_job_id, metadata_details = slurm_context_from_metadata(metadata_values or {})
    metadata_details.update(data["scheduler_details"] or {})
    data["scheduler_details"] = metadata_details
    if not data["scheduler_job_id"] and metadata_job_id:
        data["scheduler_job_id"] = metadata_job_id
    if not data["scheduler_system"] and str(data["scheduler_job_id"] or "").startswith(
        "SLURM_JOB_ID="
    ):
        data["scheduler_system"] = "slurm"
    if not data["scheduler_system"] and metadata_job_id:
        data["scheduler_system"] = "slurm"
    if not data["output_path"]:
        data["output_path"] = alamo_output_path(metadata_details)
    data["effective_status"] = effective_status(run)
    data["artifact_count"] = artifact_count
    data["artifact_previews"] = artifact_previews or []
    return RunRead.model_validate(data)


def is_preview_image(record: RunArtifact) -> bool:
    return record.kind == "image" and record.object.content_type.startswith("image/")


def artifact_preview(record: RunArtifact) -> ArtifactPreview:
    return ArtifactPreview(
        id=record.id,
        logical_name=record.logical_name,
        path=record.path,
        kind=record.kind,
        content_type=record.object.content_type,
        download_url=(
            f"/api/v1/runs/{record.run_id}/artifacts/{record.id}/content"
            if is_preview_image(record)
            else None
        ),
    )


async def artifact_previews_for_runs(
    db: AsyncSession,
    runs: list[Run],
) -> dict[uuid.UUID, tuple[int, list[ArtifactPreview]]]:
    if not runs:
        return {}
    run_ids = [run.id for run in runs]
    latest_versions = (
        select(
            RunArtifact.run_id.label("run_id"),
            RunArtifact.path.label("path"),
            func.max(RunArtifact.version).label("version"),
        )
        .where(RunArtifact.run_id.in_(run_ids))
        .group_by(RunArtifact.run_id, RunArtifact.path)
        .subquery()
    )
    current = list(
        await db.scalars(
            select(RunArtifact)
            .join(
                latest_versions,
                and_(
                    RunArtifact.run_id == latest_versions.c.run_id,
                    RunArtifact.path == latest_versions.c.path,
                    RunArtifact.version == latest_versions.c.version,
                ),
            )
            .options(selectinload(RunArtifact.object))
        )
    )
    by_run: dict[uuid.UUID, list[RunArtifact]] = {}
    by_id = {record.id: record for record in current}
    for record in current:
        by_run.setdefault(record.run_id, []).append(record)

    selected_ids = {
        run.thumbnail_artifact_id
        for run in runs
        if run.thumbnail_artifact_id and run.thumbnail_artifact_id not in by_id
    }
    if selected_ids:
        selected = list(
            await db.scalars(
                select(RunArtifact)
                .where(RunArtifact.id.in_(selected_ids))
                .options(selectinload(RunArtifact.object))
            )
        )
        by_id.update((record.id, record) for record in selected)

    result: dict[uuid.UUID, tuple[int, list[ArtifactPreview]]] = {}
    for run in runs:
        records = by_run.get(run.id, [])
        records.sort(
            key=lambda record: (
                not is_preview_image(record),
                -record.updated_at.timestamp(),
                record.path,
            )
        )
        chosen: list[RunArtifact] = []
        if (
            run.thumbnail_artifact_id
            and (selected := by_id.get(run.thumbnail_artifact_id))
            and selected.run_id == run.id
        ):
            chosen.append(selected)
        chosen_paths = {record.path for record in chosen}
        chosen.extend(record for record in records if record.path not in chosen_paths)
        result[run.id] = (
            len(records),
            [artifact_preview(record) for record in chosen[:3]],
        )
    return result


def accessible_run_ids(user: User):
    project_ids = select(Project.id).where(
        or_(
            Project.owner_id == user.id,
            Project.visibility.in_({"group", "public"}),
            Project.id.in_(
                select(ProjectMembership.project_id).where(ProjectMembership.user_id == user.id)
            ),
        )
    )
    return select(RunProject.run_id).where(RunProject.project_id.in_(project_ids))


async def get_accessible_run(db: AsyncSession, user: User, run_id: uuid.UUID) -> Run:
    run = await db.scalar(
        select(Run).where(
            Run.id == run_id,
            or_(Run.owner_id == user.id, Run.id.in_(accessible_run_ids(user))),
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("", response_model=list[RunRead])
async def list_runs(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    include_scheduler_metadata: bool = False,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Run).where(or_(Run.owner_id == user.id, Run.id.in_(accessible_run_ids(user))))
    if status_filter:
        query = query.where(Run.status == status_filter)
    if search:
        escaped = search.replace("%", r"\%").replace("_", r"\_")
        query = query.where(
            or_(
                Run.name.ilike(f"%{escaped}%"),
                Run.alamo_hash.ilike(f"%{escaped}%"),
                Run.output_path.ilike(f"%{escaped}%"),
            )
        )
    runs = list(await db.scalars(query.order_by(Run.updated_at.desc()).limit(limit)))
    previews = await artifact_previews_for_runs(db, runs)
    metadata_by_run: dict[uuid.UUID, dict[str, str]] = {}
    if include_scheduler_metadata:
        scheduler_run_ids = [
            run.id
            for run in runs
            if run.scheduler_system == "slurm"
            or str(run.scheduler_job_id or "").startswith("SLURM_JOB_ID=")
        ]
        if scheduler_run_ids:
            rows = (
                await db.execute(
                    select(RunMetadata.run_id, RunMetadata.values).where(
                        RunMetadata.run_id.in_(scheduler_run_ids)
                    )
                )
            ).all()
            metadata_by_run = {run_id: values for run_id, values in rows}
    return [
        run_read(
            run,
            *previews.get(run.id, (0, [])),
            metadata_values=metadata_by_run.get(run.id),
        )
        for run in runs
    ]


@router.post("", response_model=RunRead, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: RunCreate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    run = None
    if payload.id:
        run = await db.get(Run, payload.id)
        if run is not None and run.owner_id != user.id:
            raise HTTPException(status_code=409, detail="Run ID already exists")
    if run is None and payload.alamo_hash:
        run = await db.scalar(
            select(Run).where(Run.owner_id == user.id, Run.alamo_hash == payload.alamo_hash)
        )
    if run is None:
        values = payload.model_dump(exclude_none=True)
        run = Run(owner_id=user.id, **values)
        db.add(run)
    else:
        for key, value in payload.model_dump(exclude={"id"}, exclude_none=True).items():
            setattr(run, key, value)
    await db.commit()
    await db.refresh(run)
    return run_read(run)


@router.post("/sync-state", response_model=list[RunSyncState])
async def sync_state(
    payload: RunSyncStateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return compact fingerprints for bulk CLI synchronization."""
    rows = (
        await db.execute(
            select(Run, RunMetadata, RunOutput)
            .outerjoin(RunMetadata, RunMetadata.run_id == Run.id)
            .outerjoin(RunOutput, RunOutput.run_id == Run.id)
            .where(Run.owner_id == user.id, Run.alamo_hash.in_(payload.hashes))
        )
    ).all()
    states: list[RunSyncState] = []
    backfilled = False
    for run, metadata, output in rows:
        if run.alamo_hash is None:
            continue
        if output is not None and output.stdout_digest is None:
            output.stdout_digest = hashlib.sha256(output.stdout.encode("utf-8")).hexdigest()
            backfilled = True
        if output is not None and output.git_diff_digest is None:
            output.git_diff_digest = hashlib.sha256(output.git_diff.encode("utf-8")).hexdigest()
            backfilled = True
        states.append(
            RunSyncState(
                id=run.id,
                alamo_hash=run.alamo_hash,
                status=run.status,
                progress=run.progress,
                metadata_digest=metadata.digest if metadata else None,
                stdout_digest=output.stdout_digest if output else None,
                git_diff_digest=output.git_diff_digest if output else None,
                thermo_digest=output.thermo_digest if output else None,
            )
        )
    if backfilled:
        await db.commit()
    return states


@router.get("/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    run = await get_accessible_run(db, user, run_id)
    metadata = await db.get(RunMetadata, run.id)
    output = await db.get(RunOutput, run.id)
    series = list(
        await db.scalars(
            select(ThermoSeries)
            .where(ThermoSeries.run_id == run.id)
            .options(selectinload(ThermoSeries.points))
            .order_by(ThermoSeries.segment)
        )
    )
    return {
        "run": run_read(run, metadata_values=metadata.values if metadata else None),
        "metadata": MetadataRead.model_validate(metadata) if metadata else None,
        "output": RunOutputRead.model_validate(output) if output else None,
        "thermo": [
            ThermoSeriesRead(
                segment=item.segment,
                columns=item.columns,
                rows=[
                    ThermoRow(sequence=point.sequence, values=point.values) for point in item.points
                ],
            )
            for item in series
        ],
    }


@router.patch("/{run_id}", response_model=RunRead)
async def update_run(
    run_id: uuid.UUID,
    payload: RunUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can edit this run")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(run, key, value)
    await db.commit()
    await db.refresh(run)
    return run_read(run)


@router.delete("/{run_id}", status_code=204)
async def delete_run(
    run_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete this run")
    await db.delete(run)
    await db.commit()


@router.post("/{run_id}/heartbeat", response_model=RunRead)
async def heartbeat(
    run_id: uuid.UUID,
    payload: Heartbeat,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can post telemetry")
    if payload.sequence > run.event_sequence:
        run.event_sequence = payload.sequence
        run.status = payload.status
        run.progress = payload.progress
        run.last_heartbeat = payload.observed_at or utcnow()
        if payload.status in {"completed", "failed", "interrupted"}:
            run.ended_at = payload.observed_at or utcnow()
        await db.commit()
        await db.refresh(run)
    return run_read(run)


@router.put("/{run_id}/metadata", response_model=MetadataRead)
async def write_metadata(
    run_id: uuid.UUID,
    payload: MetadataWrite,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can post metadata")
    parsed = parse_metadata(payload.raw_text)
    record = await db.get(RunMetadata, run.id)
    if record is None:
        record = RunMetadata(run_id=run.id)
        db.add(record)
    record.raw_text = payload.raw_text
    record.values = parsed.values
    record.sections = parsed.sections
    record.digest = parsed.digest
    run.alamo_hash = parsed.values.get("HASH", run.alamo_hash)
    run.git_commit = parsed.values.get("Git_commit_hash", run.git_commit)
    run.host = parsed.values.get("Platform", run.host)
    metadata_job_id, metadata_details = slurm_context_from_metadata(parsed.values)
    scheduler_details = dict(run.scheduler_details or {})
    for key, value in metadata_details.items():
        if not scheduler_details.get(key):
            scheduler_details[key] = value
    run.scheduler_details = scheduler_details
    if metadata_job_id:
        run.scheduler_job_id = run.scheduler_job_id or metadata_job_id
        run.scheduler_system = run.scheduler_system or "slurm"
    if not run.output_path:
        run.output_path = alamo_output_path(scheduler_details)
    derived_status, progress = status_from_metadata(parsed.values)
    if derived_status:
        run.status = derived_status
    if progress is not None:
        run.progress = progress
    await db.commit()
    await db.refresh(record)
    return MetadataRead.model_validate(record)


@router.put("/{run_id}/output", response_model=RunOutputRead)
async def write_output(
    run_id: uuid.UUID,
    payload: RunOutputWrite,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can post run output")
    record = await db.get(RunOutput, run.id)
    if record is None:
        record = RunOutput(run_id=run.id)
        db.add(record)
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "stdout" in values:
        record.stdout_digest = hashlib.sha256(values["stdout"].encode("utf-8")).hexdigest()
    if "git_diff" in values:
        record.git_diff_digest = hashlib.sha256(
            values["git_diff"].encode("utf-8")
        ).hexdigest()
    for key, value in values.items():
        setattr(record, key, value)
    await db.commit()
    await db.refresh(record)
    return RunOutputRead.model_validate(record)


@router.post("/{run_id}/thermo", status_code=202)
async def append_thermo(
    run_id: uuid.UUID,
    payload: ThermoBatch,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can post telemetry")
    series = await db.scalar(
        select(ThermoSeries).where(
            ThermoSeries.run_id == run.id, ThermoSeries.segment == payload.segment
        )
    )
    if series is None:
        series = ThermoSeries(run_id=run.id, segment=payload.segment, columns=payload.columns)
        db.add(series)
        await db.flush()
    elif series.columns != payload.columns:
        raise HTTPException(status_code=409, detail="Column schema differs within a segment")

    existing = set(
        await db.scalars(
            select(ThermoPoint.sequence).where(
                ThermoPoint.series_id == series.id,
                ThermoPoint.sequence.in_([row.sequence for row in payload.rows]),
            )
        )
    )
    inserted = 0
    for row in payload.rows:
        if row.sequence in existing:
            continue
        values = {column: row.values.get(column) for column in payload.columns}
        db.add(ThermoPoint(series_id=series.id, sequence=row.sequence, values=values))
        inserted += 1
    await db.commit()
    return {"accepted": inserted, "duplicates": len(payload.rows) - inserted}
