from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import Settings, get_settings
from ..db import get_db
from ..dependencies import current_user
from ..models import (
    ArtifactObject,
    Project,
    ProjectFolder,
    ProjectMembership,
    Run,
    RunArtifact,
    RunProject,
    User,
    utcnow,
)
from ..schemas import (
    ArtifactPreview,
    ProjectCreate,
    ProjectDashboardRead,
    ProjectFolderCreate,
    ProjectFolderRead,
    ProjectFolderUpdate,
    ProjectGalleryItem,
    ProjectLayoutRead,
    ProjectMemberAdd,
    ProjectMemberRead,
    ProjectRead,
    ProjectRunAdd,
    ProjectRunBatchAdd,
    ProjectRunBatchResult,
    ProjectRunPlacementBatchWrite,
    ProjectRunPlacementRead,
    ProjectRunPlacementWrite,
    ProjectUpdate,
)
from .runs import (
    HEARTBEAT_GRACE,
    artifact_preview,
    artifact_previews_for_runs,
    copy_counts_for_runs,
    run_read,
)

router = APIRouter(prefix="/projects", tags=["projects"])


async def accessible_project(db: AsyncSession, user: User, project_id: uuid.UUID) -> Project:
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            or_(
                Project.owner_id == user.id,
                Project.visibility.in_({"group", "public"}),
                Project.id.in_(
                    select(ProjectMembership.project_id).where(ProjectMembership.user_id == user.id)
                ),
            ),
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def editable_project(db: AsyncSession, user: User, project_id: uuid.UUID) -> Project:
    project = await accessible_project(db, user, project_id)
    if project.owner_id == user.id:
        return project
    membership = await db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == user.id,
            ProjectMembership.role.in_({"owner", "editor"}),
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Project edit access required")
    return project


async def project_folder(
    db: AsyncSession,
    project_id: uuid.UUID,
    folder_id: uuid.UUID,
) -> ProjectFolder:
    folder = await db.get(ProjectFolder, folder_id)
    if folder is None or folder.project_id != project_id:
        raise HTTPException(status_code=404, detail="Project folder not found")
    return folder


async def validate_parent_folder(
    db: AsyncSession,
    project_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    folder_id: uuid.UUID | None = None,
) -> None:
    seen: set[uuid.UUID] = set()
    current_id = parent_id
    while current_id is not None:
        if current_id == folder_id or current_id in seen:
            raise HTTPException(status_code=422, detail="Folders cannot contain themselves")
        seen.add(current_id)
        current = await project_folder(db, project_id, current_id)
        current_id = current.parent_id


async def ensure_unique_folder_name(
    db: AsyncSession,
    project_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    name: str,
    folder_id: uuid.UUID | None = None,
) -> None:
    query = select(ProjectFolder.id).where(
        ProjectFolder.project_id == project_id,
        ProjectFolder.parent_id == parent_id,
        func.lower(ProjectFolder.name) == name.lower(),
    )
    if folder_id is not None:
        query = query.where(ProjectFolder.id != folder_id)
    if await db.scalar(query):
        raise HTTPException(status_code=409, detail="A folder with this name already exists here")


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    editable: bool = Query(default=False),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    member_projects = select(ProjectMembership.project_id).where(
        ProjectMembership.user_id == user.id
    )
    if editable:
        member_projects = member_projects.where(ProjectMembership.role.in_({"owner", "editor"}))
        access = or_(Project.owner_id == user.id, Project.id.in_(member_projects))
    else:
        access = or_(
            Project.owner_id == user.id,
            Project.visibility.in_({"group", "public"}),
            Project.id.in_(member_projects),
        )
    return list(await db.scalars(select(Project).where(access).order_by(Project.name)))


@router.get("/dashboard", response_model=list[ProjectDashboardRead])
async def project_dashboard(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectDashboardRead]:
    member_projects = select(ProjectMembership.project_id).where(
        ProjectMembership.user_id == user.id
    )
    access = or_(
        Project.owner_id == user.id,
        Project.visibility.in_({"group", "public"}),
        Project.id.in_(member_projects),
    )
    stale_before = utcnow() - HEARTBEAT_GRACE
    active_run = (
        Run.status.in_({"starting", "running"})
        & Run.last_heartbeat.is_not(None)
        & (Run.last_heartbeat >= stale_before)
    )
    activity = (
        select(
            RunProject.project_id.label("project_id"),
            func.count(Run.id).label("run_count"),
            func.count(Run.id).filter(active_run).label("active_run_count"),
            func.max(Run.updated_at).label("last_run_at"),
        )
        .join(Run, Run.id == RunProject.run_id)
        .group_by(RunProject.project_id)
        .subquery()
    )
    last_modified = case(
        (activity.c.last_run_at.is_(None), Project.updated_at),
        (Project.updated_at >= activity.c.last_run_at, Project.updated_at),
        else_=activity.c.last_run_at,
    )
    rows = (
        await db.execute(
            select(
                Project,
                func.coalesce(activity.c.run_count, 0),
                func.coalesce(activity.c.active_run_count, 0),
                last_modified.label("last_modified_at"),
            )
            .outerjoin(activity, activity.c.project_id == Project.id)
            .where(access)
            .order_by(last_modified.desc(), Project.name)
        )
    ).all()

    project_ids = [project.id for project, *_ in rows]
    thumbnails_by_project: dict[uuid.UUID, list[ArtifactPreview]] = {
        project_id: [] for project_id in project_ids
    }
    if project_ids:
        latest_versions = (
            select(
                RunProject.project_id.label("project_id"),
                RunArtifact.run_id.label("run_id"),
                RunArtifact.path.label("path"),
                func.max(RunArtifact.version).label("version"),
            )
            .join(RunArtifact, RunArtifact.run_id == RunProject.run_id)
            .where(RunProject.project_id.in_(project_ids))
            .group_by(RunProject.project_id, RunArtifact.run_id, RunArtifact.path)
            .subquery()
        )
        is_selected = Run.thumbnail_artifact_id == RunArtifact.id
        is_current = and_(
            RunArtifact.run_id == latest_versions.c.run_id,
            RunArtifact.path == latest_versions.c.path,
            RunArtifact.version == latest_versions.c.version,
        )
        is_image = func.lower(ArtifactObject.content_type).like("image/%")
        candidates = (
            select(
                RunProject.project_id.label("project_id"),
                RunArtifact.id.label("artifact_id"),
                func.row_number()
                .over(
                    partition_by=RunProject.project_id,
                    order_by=(
                        case((is_selected, 0), else_=1),
                        case((is_image, 0), else_=1),
                        RunArtifact.updated_at.desc(),
                    ),
                )
                .label("rank"),
            )
            .join(Run, Run.id == RunProject.run_id)
            .join(RunArtifact, RunArtifact.run_id == Run.id)
            .join(ArtifactObject, ArtifactObject.sha256 == RunArtifact.object_sha256)
            .outerjoin(
                latest_versions,
                and_(
                    latest_versions.c.project_id == RunProject.project_id,
                    latest_versions.c.run_id == RunArtifact.run_id,
                    latest_versions.c.path == RunArtifact.path,
                ),
            )
            .where(
                RunProject.project_id.in_(project_ids),
                or_(
                    func.lower(ArtifactObject.content_type).like("image/%"),
                    func.lower(ArtifactObject.content_type).like("video/%"),
                ),
                or_(is_selected, is_current),
            )
            .subquery()
        )
        preview_rows = (
            await db.execute(
                select(candidates.c.project_id, RunArtifact)
                .join(RunArtifact, RunArtifact.id == candidates.c.artifact_id)
                .where(candidates.c.rank <= 3)
                .options(selectinload(RunArtifact.object))
                .order_by(candidates.c.project_id, candidates.c.rank)
            )
        ).all()
        for project_id, record in preview_rows:
            thumbnails_by_project[project_id].append(artifact_preview(record))
    return [
        ProjectDashboardRead(
            id=project.id,
            owner_id=project.owner_id,
            slug=project.slug,
            name=project.name,
            description=project.description,
            visibility=project.visibility,
            created_at=project.created_at,
            updated_at=project.updated_at,
            last_modified_at=last_modified_at,
            run_count=run_count,
            active_run_count=active_run_count,
            artifact_previews=thumbnails_by_project[project.id],
        )
        for project, run_count, active_run_count, last_modified_at in rows
    ]


@router.get("/{project_id}/gallery", response_model=list[ProjectGalleryItem])
async def project_gallery(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectGalleryItem]:
    project = await accessible_project(db, user, project_id)
    is_selected = Run.thumbnail_artifact_id == RunArtifact.id
    is_visual = or_(
        func.lower(ArtifactObject.content_type).like("image/%"),
        func.lower(ArtifactObject.content_type).like("video/%"),
    )
    preferred_versions = (
        select(
            RunArtifact.id.label("artifact_id"),
            func.row_number()
            .over(
                partition_by=(RunArtifact.run_id, RunArtifact.path),
                order_by=(case((is_selected, 0), else_=1), RunArtifact.version.desc()),
            )
            .label("rank"),
        )
        .join(Run, Run.id == RunArtifact.run_id)
        .join(RunProject, RunProject.run_id == Run.id)
        .join(ArtifactObject, ArtifactObject.sha256 == RunArtifact.object_sha256)
        .where(RunProject.project_id == project.id, is_visual)
        .subquery()
    )
    selected_artifact = Run.thumbnail_artifact_id == RunArtifact.id
    rows = (
        await db.execute(
            select(RunArtifact, Run.name, selected_artifact.label("is_thumbnail"))
            .join(preferred_versions, preferred_versions.c.artifact_id == RunArtifact.id)
            .join(Run, Run.id == RunArtifact.run_id)
            .where(preferred_versions.c.rank == 1)
            .options(selectinload(RunArtifact.object))
            .order_by(
                case((selected_artifact, 0), else_=1),
                RunArtifact.updated_at.desc(),
            )
            .limit(500)
        )
    ).all()
    return [
        ProjectGalleryItem(
            **artifact_preview(record).model_dump(),
            run_id=record.run_id,
            run_name=run_name,
            is_thumbnail=bool(is_thumbnail),
            updated_at=record.updated_at,
        )
        for record, run_name, is_thumbnail in rows
    ]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if await db.scalar(select(Project.id).where(Project.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="Project slug is already in use")
    project = Project(owner_id=user.id, **payload.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Owned project not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Owned project not found")
    await db.delete(project)
    await db.commit()


@router.get("/{project_id}/layout", response_model=ProjectLayoutRead)
async def project_layout(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectLayoutRead:
    project = await accessible_project(db, user, project_id)
    folders = list(
        await db.scalars(
            select(ProjectFolder)
            .where(ProjectFolder.project_id == project.id)
            .order_by(ProjectFolder.position, ProjectFolder.name)
        )
    )
    rows = (
        await db.execute(
            select(Run, RunProject)
            .join(RunProject, RunProject.run_id == Run.id)
            .where(RunProject.project_id == project.id)
            .order_by(RunProject.position, Run.name)
        )
    ).all()
    runs = [run for run, _ in rows]
    previews = await artifact_previews_for_runs(db, runs)
    copy_counts = await copy_counts_for_runs(db, runs)
    return ProjectLayoutRead(
        folders=[ProjectFolderRead.model_validate(folder) for folder in folders],
        runs=[
            ProjectRunPlacementRead(
                run=run_read(
                    run,
                    *previews.get(run.id, (0, [])),
                    copy_count=copy_counts.get(run.id, 0),
                ),
                folder_id=link.folder_id,
                position=link.position,
            )
            for run, link in rows
        ],
    )


@router.post(
    "/{project_id}/folders",
    response_model=ProjectFolderRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    project_id: uuid.UUID,
    payload: ProjectFolderCreate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await editable_project(db, user, project_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Folder name cannot be blank")
    await validate_parent_folder(db, project.id, payload.parent_id)
    await ensure_unique_folder_name(db, project.id, payload.parent_id, name)
    last_position = await db.scalar(
        select(func.coalesce(func.max(ProjectFolder.position), -1)).where(
            ProjectFolder.project_id == project.id,
            ProjectFolder.parent_id == payload.parent_id,
        )
    )
    position = (last_position if last_position is not None else -1) + 1
    folder = ProjectFolder(
        project_id=project.id,
        parent_id=payload.parent_id,
        name=name,
        position=position,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.patch("/{project_id}/folders/{folder_id}", response_model=ProjectFolderRead)
async def update_folder(
    project_id: uuid.UUID,
    folder_id: uuid.UUID,
    payload: ProjectFolderUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await editable_project(db, user, project_id)
    folder = await project_folder(db, project.id, folder_id)
    parent_id = payload.parent_id if "parent_id" in payload.model_fields_set else folder.parent_id
    name = payload.name.strip() if payload.name is not None else folder.name
    if not name:
        raise HTTPException(status_code=422, detail="Folder name cannot be blank")
    await validate_parent_folder(db, project.id, parent_id, folder.id)
    await ensure_unique_folder_name(db, project.id, parent_id, name, folder.id)
    folder.parent_id = parent_id
    folder.name = name
    if payload.position is not None:
        folder.position = payload.position
    await db.commit()
    await db.refresh(folder)
    return folder


@router.delete("/{project_id}/folders/{folder_id}", status_code=204)
async def delete_folder(
    project_id: uuid.UUID,
    folder_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await editable_project(db, user, project_id)
    folder = await project_folder(db, project.id, folder_id)
    has_children = await db.scalar(
        select(ProjectFolder.id).where(ProjectFolder.parent_id == folder.id).limit(1)
    )
    has_runs = await db.scalar(
        select(RunProject.run_id).where(RunProject.folder_id == folder.id).limit(1)
    )
    if has_children or has_runs:
        raise HTTPException(status_code=409, detail="Only empty folders can be deleted")
    await db.delete(folder)
    await db.commit()


@router.get("/{project_id}/members", response_model=list[ProjectMemberRead])
async def list_members(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await accessible_project(db, user, project_id)
    if project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Project owner access required")
    rows = await db.execute(
        select(ProjectMembership, User)
        .join(User, User.id == ProjectMembership.user_id)
        .where(ProjectMembership.project_id == project.id)
        .order_by(User.email)
    )
    return [
        ProjectMemberRead(
            id=membership.id,
            user_id=member.id,
            email=member.email,
            name=member.name,
            role=membership.role,
        )
        for membership, member in rows
    ]


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    project_id: uuid.UUID,
    payload: ProjectMemberAdd,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    project = await db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Owned project not found")
    email = str(payload.email).lower()
    if not email.endswith(f"@{settings.google_allowed_domain}"):
        raise HTTPException(
            status_code=422,
            detail=f"Project members must use @{settings.google_allowed_domain}",
        )
    member = await db.scalar(select(User).where(User.email == email))
    if member is None:
        member = User(email=email, name=email.split("@", 1)[0])
        db.add(member)
        await db.flush()
    if member.id == user.id:
        raise HTTPException(status_code=409, detail="The project owner already has access")
    membership = await db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == member.id,
        )
    )
    if membership is None:
        membership = ProjectMembership(project_id=project.id, user_id=member.id, role=payload.role)
        db.add(membership)
    else:
        membership.role = payload.role
    await db.commit()
    await db.refresh(membership)
    return ProjectMemberRead(
        id=membership.id,
        user_id=member.id,
        email=member.email,
        name=member.name,
        role=membership.role,
    )


@router.delete("/{project_id}/members/{membership_id}", status_code=204)
async def remove_member(
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Owned project not found")
    membership = await db.get(ProjectMembership, membership_id)
    if membership is None or membership.project_id != project.id:
        raise HTTPException(status_code=404, detail="Membership not found")
    await db.delete(membership)
    await db.commit()


@router.post("/{project_id}/runs", status_code=204)
async def add_run(
    project_id: uuid.UUID,
    payload: ProjectRunAdd,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await editable_project(db, user, project_id)
    if payload.folder_id is not None:
        await project_folder(db, project.id, payload.folder_id)
    run = await db.get(Run, payload.run_id)
    if run is None or run.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Owned run not found")
    if await db.get(RunProject, (run.id, project.id)) is None:
        db.add(
            RunProject(
                run_id=run.id,
                project_id=project.id,
                folder_id=payload.folder_id,
            )
        )
        await db.commit()


@router.post("/{project_id}/runs/batch", response_model=ProjectRunBatchResult)
async def add_runs_batch(
    project_id: uuid.UUID,
    payload: ProjectRunBatchAdd,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectRunBatchResult:
    project = await editable_project(db, user, project_id)
    if payload.folder_id is not None:
        await project_folder(db, project.id, payload.folder_id)

    run_ids = set(payload.run_ids)
    owned_run_ids = set(
        await db.scalars(select(Run.id).where(Run.id.in_(run_ids), Run.owner_id == user.id))
    )
    if owned_run_ids != run_ids:
        raise HTTPException(status_code=404, detail="One or more owned runs were not found")

    existing_ids = set(
        await db.scalars(
            select(RunProject.run_id).where(
                RunProject.project_id == project.id,
                RunProject.run_id.in_(run_ids),
            )
        )
    )
    new_ids = run_ids - existing_ids
    db.add_all(
        RunProject(
            run_id=run_id,
            project_id=project.id,
            folder_id=payload.folder_id,
        )
        for run_id in new_ids
    )
    if new_ids:
        await db.commit()
    return ProjectRunBatchResult(added=len(new_ids), already_present=len(existing_ids))


@router.get("/{project_id}/runs")
async def list_project_runs(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await accessible_project(db, user, project_id)
    runs = list(
        await db.scalars(
            select(Run)
            .join(RunProject, RunProject.run_id == Run.id)
            .where(RunProject.project_id == project.id)
            .order_by(Run.updated_at.desc())
        )
    )
    previews = await artifact_previews_for_runs(db, runs)
    copy_counts = await copy_counts_for_runs(db, runs)
    return [
        run_read(
            run,
            *previews.get(run.id, (0, [])),
            copy_count=copy_counts.get(run.id, 0),
        )
        for run in runs
    ]


@router.put(
    "/{project_id}/runs/placement/batch",
    response_model=list[ProjectRunPlacementRead],
)
async def place_runs(
    project_id: uuid.UUID,
    payload: ProjectRunPlacementBatchWrite,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectRunPlacementRead]:
    project = await editable_project(db, user, project_id)
    if payload.folder_id is not None:
        await project_folder(db, project.id, payload.folder_id)
    run_ids = list(dict.fromkeys(payload.run_ids))
    links = list(
        await db.scalars(
            select(RunProject).where(
                RunProject.project_id == project.id,
                RunProject.run_id.in_(run_ids),
            )
        )
    )
    if {link.run_id for link in links} != set(run_ids):
        raise HTTPException(status_code=404, detail="One or more runs are not in this project")
    runs = list(await db.scalars(select(Run).where(Run.id.in_(run_ids))))
    runs_by_id = {run.id: run for run in runs}
    links_by_id = {link.run_id: link for link in links}
    for offset, run_id in enumerate(run_ids):
        links_by_id[run_id].folder_id = payload.folder_id
        links_by_id[run_id].position = payload.position + offset
    await db.commit()
    return [
        ProjectRunPlacementRead(
            run=run_read(runs_by_id[run_id]),
            folder_id=links_by_id[run_id].folder_id,
            position=links_by_id[run_id].position,
        )
        for run_id in run_ids
    ]


@router.put(
    "/{project_id}/runs/{run_id}/placement",
    response_model=ProjectRunPlacementRead,
)
async def place_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: ProjectRunPlacementWrite,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectRunPlacementRead:
    project = await editable_project(db, user, project_id)
    if payload.folder_id is not None:
        await project_folder(db, project.id, payload.folder_id)
    link = await db.get(RunProject, (run_id, project.id))
    if link is None:
        raise HTTPException(status_code=404, detail="Run is not in this project")
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    link.folder_id = payload.folder_id
    link.position = payload.position
    await db.commit()
    return ProjectRunPlacementRead(
        run=run_read(run),
        folder_id=link.folder_id,
        position=link.position,
    )


@router.delete("/{project_id}/runs/{run_id}", status_code=204)
async def remove_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await accessible_project(db, user, project_id)
    if project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Project owner access required")
    link = await db.get(RunProject, (run_id, project.id))
    if link:
        await db.delete(link)
        await db.commit()
