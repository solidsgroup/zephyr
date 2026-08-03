from __future__ import annotations

import pathlib
import uuid

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..dependencies import current_user
from ..models import ArtifactObject, RunArtifact, User
from ..schemas import (
    ArtifactComplete,
    ArtifactInitiate,
    ArtifactInitiated,
    ArtifactRead,
)
from ..storage import ObjectStorage, get_storage
from .runs import get_accessible_run

router = APIRouter(prefix="/runs/{run_id}/artifacts", tags=["artifacts"])


def safe_relative_path(path: str) -> str:
    candidate = pathlib.PurePosixPath(path.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise HTTPException(status_code=422, detail="Artifact path must be relative and safe")
    return candidate.as_posix()


def artifact_read(record: RunArtifact, download_url: str | None = None) -> ArtifactRead:
    return ArtifactRead(
        id=record.id,
        sha256=record.object.sha256,
        size=record.object.size,
        content_type=record.object.content_type,
        logical_name=record.logical_name,
        path=record.path,
        version=record.version,
        kind=record.kind,
        attributes=record.attributes,
        derivation=record.derivation,
        download_url=download_url,
    )


@router.post("/initiate", response_model=ArtifactInitiated)
async def initiate_upload(
    run_id: uuid.UUID,
    payload: ArtifactInitiate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
):
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can upload artifacts")
    existing = await db.get(ArtifactObject, payload.sha256)
    if existing and existing.verified:
        return ArtifactInitiated(already_present=True)
    if existing is None:
        existing = ArtifactObject(
            sha256=payload.sha256,
            size=payload.size,
            content_type=payload.content_type,
            object_key=storage.key_for(payload.sha256),
        )
        db.add(existing)
        await db.commit()
    elif existing.size != payload.size:
        raise HTTPException(status_code=409, detail="Digest already exists with a different size")
    url, headers = storage.presign_put(payload.sha256, payload.content_type)
    return ArtifactInitiated(already_present=False, upload_url=url, headers=headers)


@router.post("/complete", response_model=ArtifactRead, status_code=status.HTTP_201_CREATED)
async def complete_upload(
    run_id: uuid.UUID,
    payload: ArtifactComplete,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
):
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can upload artifacts")
    obj = await db.get(ArtifactObject, payload.sha256)
    if obj is None:
        raise HTTPException(status_code=409, detail="Upload was not initiated")
    if not obj.verified:
        try:
            head = storage.head(obj.object_key)
        except ClientError as error:
            raise HTTPException(status_code=409, detail="Uploaded object was not found") from error
        if int(head.get("ContentLength", -1)) != obj.size:
            raise HTTPException(status_code=409, detail="Uploaded object size does not match")
        if head.get("Metadata", {}).get("sha256") != obj.sha256:
            raise HTTPException(
                status_code=409, detail="Uploaded object digest metadata is missing"
            )
        obj.verified = True

    path = safe_relative_path(payload.path)
    latest = await db.scalar(
        select(func.max(RunArtifact.version)).where(
            RunArtifact.run_id == run.id, RunArtifact.path == path
        )
    )
    record = RunArtifact(
        run_id=run.id,
        object_sha256=obj.sha256,
        path=path,
        logical_name=payload.logical_name or pathlib.PurePosixPath(path).name,
        version=(latest or 0) + 1,
        kind=payload.kind,
        attributes=payload.attributes,
        derivation=payload.derivation,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record, attribute_names=["object"])
    return artifact_read(record)


@router.get("", response_model=list[ArtifactRead])
async def list_artifacts(
    run_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_accessible_run(db, user, run_id)
    records = list(
        await db.scalars(
            select(RunArtifact)
            .where(RunArtifact.run_id == run_id)
            .order_by(RunArtifact.path, RunArtifact.version.desc())
        )
    )
    for record in records:
        await db.refresh(record, attribute_names=["object"])
    return [artifact_read(record) for record in records]


@router.get("/{artifact_id}/download", response_model=ArtifactRead)
async def download_artifact(
    run_id: uuid.UUID,
    artifact_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
):
    await get_accessible_run(db, user, run_id)
    record = await db.get(RunArtifact, artifact_id)
    if record is None or record.run_id != run_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    await db.refresh(record, attribute_names=["object"])
    return artifact_read(record, storage.presign_get(record.object.object_key))
