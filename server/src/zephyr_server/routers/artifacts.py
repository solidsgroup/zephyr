from __future__ import annotations

import pathlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..artifact_links import artifact_download_url, decode_download_token
from ..config import Settings, get_settings
from ..db import get_db
from ..dependencies import current_user
from ..models import ArtifactObject, RunArtifact, User
from ..schemas import (
    ArtifactComplete,
    ArtifactInitiate,
    ArtifactInitiated,
    ArtifactRead,
    RunRead,
)
from ..storage import GoogleDriveStorage, StorageError, StoredObjectNotFound, get_storage
from .runs import get_accessible_run, run_read

router = APIRouter(prefix="/runs/{run_id}/artifacts", tags=["artifacts"])
content_router = APIRouter(prefix="/artifacts", tags=["artifacts"])


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


@content_router.get("/content/{token}", include_in_schema=False)
def artifact_content(
    token: str,
    settings: Settings = Depends(get_settings),
    storage: GoogleDriveStorage = Depends(get_storage),
) -> StreamingResponse:
    object_key, content_type = decode_download_token(settings, token)
    try:
        content = storage.open_download(object_key)
    except StoredObjectNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except StorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return StreamingResponse(
        content,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/initiate", response_model=ArtifactInitiated)
async def initiate_upload(
    run_id: uuid.UUID,
    payload: ArtifactInitiate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    storage: GoogleDriveStorage = Depends(get_storage),
):
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can upload artifacts")
    existing = await db.get(ArtifactObject, payload.sha256)
    if existing and existing.verified:
        return ArtifactInitiated(already_present=True)
    if existing is not None and existing.size != payload.size:
        raise HTTPException(status_code=409, detail="Digest already exists with a different size")
    if existing is not None:
        try:
            storage.verify(existing.object_key, existing.sha256, existing.size)
        except StoredObjectNotFound:
            pass
        except StorageError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        else:
            existing.verified = True
            await db.commit()
            return ArtifactInitiated(already_present=True)
    try:
        target = storage.initiate_upload(
            payload.sha256,
            payload.size,
            payload.content_type,
            existing.object_key if existing else None,
        )
    except StorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if existing is None:
        db.add(
            ArtifactObject(
                sha256=payload.sha256,
                size=payload.size,
                content_type=payload.content_type,
                object_key=target.object_key,
            )
        )
        await db.commit()
    return ArtifactInitiated(
        already_present=False,
        upload_url=target.url,
        headers=target.headers,
    )


@router.post("/complete", response_model=ArtifactRead, status_code=status.HTTP_201_CREATED)
async def complete_upload(
    run_id: uuid.UUID,
    payload: ArtifactComplete,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    storage: GoogleDriveStorage = Depends(get_storage),
):
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can upload artifacts")
    obj = await db.get(ArtifactObject, payload.sha256)
    if obj is None:
        raise HTTPException(status_code=409, detail="Upload was not initiated")
    if not obj.verified:
        try:
            storage.verify(obj.object_key, obj.sha256, obj.size)
        except StoredObjectNotFound as error:
            raise HTTPException(status_code=409, detail="Uploaded object was not found") from error
        except StorageError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
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


@router.put("/{artifact_id}/thumbnail", response_model=RunRead)
async def select_thumbnail(
    run_id: uuid.UUID,
    artifact_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await get_accessible_run(db, user, run_id)
    if run.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can select a thumbnail")
    record = await db.get(RunArtifact, artifact_id)
    if record is None or record.run_id != run.id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    await db.refresh(record, attribute_names=["object"])
    if record.kind != "image" or not record.object.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Only image artifacts can be thumbnails")
    run.thumbnail_artifact_id = record.id
    await db.commit()
    await db.refresh(run)
    return run_read(run)


@router.get("/{artifact_id}/content", include_in_schema=False)
async def preview_artifact_content(
    run_id: uuid.UUID,
    artifact_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    storage: GoogleDriveStorage = Depends(get_storage),
) -> StreamingResponse:
    await get_accessible_run(db, user, run_id)
    record = await db.get(RunArtifact, artifact_id)
    if record is None or record.run_id != run_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    await db.refresh(record, attribute_names=["object"])
    if record.kind != "image" or not record.object.content_type.startswith("image/"):
        raise HTTPException(status_code=404, detail="Image preview not found")
    try:
        content = storage.open_download(record.object.object_key)
    except StoredObjectNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except StorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return StreamingResponse(
        content,
        media_type=record.object.content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/{artifact_id}/download", response_model=ArtifactRead)
async def download_artifact(
    run_id: uuid.UUID,
    artifact_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    await get_accessible_run(db, user, run_id)
    record = await db.get(RunArtifact, artifact_id)
    if record is None or record.run_id != run_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    await db.refresh(record, attribute_names=["object"])
    return artifact_read(
        record,
        artifact_download_url(settings, record.object.object_key, record.object.content_type),
    )
