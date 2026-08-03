from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Project, Run, RunArtifact, RunMetadata, RunProject, ThermoSeries
from ..schemas import MetadataRead, ProjectRead, ThermoRow, ThermoSeriesRead
from .artifacts import artifact_download_url, artifact_read
from .runs import run_read

router = APIRouter(prefix="/public", tags=["public sharing"])


async def public_project(db: AsyncSession, slug: str) -> Project:
    project = await db.scalar(
        select(Project).where(Project.slug == slug, Project.visibility == "public")
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Public project not found")
    return project


@router.get("/projects", response_model=list[ProjectRead])
async def list_public_projects(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    return list(
        await db.scalars(
            select(Project)
            .where(Project.visibility == "public")
            .order_by(Project.updated_at.desc())
            .limit(limit)
        )
    )


@router.get("/projects/{slug}")
async def show_public_project(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await public_project(db, slug)
    runs = list(
        await db.scalars(
            select(Run)
            .join(RunProject, RunProject.run_id == Run.id)
            .where(RunProject.project_id == project.id)
            .order_by(Run.updated_at.desc())
        )
    )
    return {
        "project": ProjectRead.model_validate(project),
        "runs": [run_read(run) for run in runs],
    }


@router.get("/projects/{slug}/runs/{run_id}")
async def show_public_run(
    slug: str,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    project = await public_project(db, slug)
    run = await db.scalar(
        select(Run)
        .join(RunProject, RunProject.run_id == Run.id)
        .where(Run.id == run_id, RunProject.project_id == project.id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Public run not found")
    metadata = await db.get(RunMetadata, run.id)
    thermo = list(
        await db.scalars(
            select(ThermoSeries)
            .where(ThermoSeries.run_id == run.id)
            .options(selectinload(ThermoSeries.points))
            .order_by(ThermoSeries.segment)
        )
    )
    artifacts = list(
        await db.scalars(
            select(RunArtifact)
            .where(RunArtifact.run_id == run.id)
            .options(selectinload(RunArtifact.object))
            .order_by(RunArtifact.path, RunArtifact.version.desc())
        )
    )
    return {
        "project": ProjectRead.model_validate(project),
        "run": run_read(run),
        "metadata": MetadataRead.model_validate(metadata) if metadata else None,
        "thermo": [
            ThermoSeriesRead(
                segment=series.segment,
                columns=series.columns,
                rows=[
                    ThermoRow(sequence=point.sequence, values=point.values)
                    for point in series.points
                ],
            )
            for series in thermo
        ],
        "artifacts": [
            artifact_read(
                record,
                artifact_download_url(
                    settings, record.object.object_key, record.object.content_type
                ),
            )
            for record in artifacts
        ],
    }
