from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..dependencies import current_user
from ..metadata import parse_metadata, status_from_metadata
from ..models import (
    Project,
    ProjectMembership,
    Run,
    RunMetadata,
    RunProject,
    ThermoPoint,
    ThermoSeries,
    User,
    ensure_utc,
    utcnow,
)
from ..schemas import (
    Heartbeat,
    MetadataRead,
    MetadataWrite,
    RunCreate,
    RunRead,
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


def run_read(run: Run) -> RunRead:
    data = {column.name: getattr(run, column.name) for column in Run.__table__.columns}
    data["effective_status"] = effective_status(run)
    return RunRead.model_validate(data)


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
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Run).where(or_(Run.owner_id == user.id, Run.id.in_(accessible_run_ids(user))))
    if status_filter:
        query = query.where(Run.status == status_filter)
    if search:
        escaped = search.replace("%", r"\%").replace("_", r"\_")
        query = query.where(
            or_(Run.name.ilike(f"%{escaped}%"), Run.alamo_hash.ilike(f"%{escaped}%"))
        )
    runs = list(await db.scalars(query.order_by(Run.updated_at.desc()).limit(limit)))
    return [run_read(run) for run in runs]


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


@router.get("/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    run = await get_accessible_run(db, user, run_id)
    metadata = await db.get(RunMetadata, run.id)
    series = list(
        await db.scalars(
            select(ThermoSeries)
            .where(ThermoSeries.run_id == run.id)
            .options(selectinload(ThermoSeries.points))
            .order_by(ThermoSeries.segment)
        )
    )
    return {
        "run": run_read(run),
        "metadata": MetadataRead.model_validate(metadata) if metadata else None,
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
    derived_status, progress = status_from_metadata(parsed.values)
    if derived_status:
        run.status = derived_status
    if progress is not None:
        run.progress = progress
    await db.commit()
    await db.refresh(record)
    return MetadataRead.model_validate(record)


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
