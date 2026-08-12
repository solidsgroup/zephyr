from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db import get_db
from ..dependencies import current_user
from ..models import Project, ProjectMembership, Run, RunProject, User
from ..schemas import (
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberRead,
    ProjectRead,
    ProjectRunAdd,
    ProjectRunBatchAdd,
    ProjectRunBatchResult,
    ProjectUpdate,
)
from .runs import run_read

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
    project = await accessible_project(db, user, project_id)
    if project.owner_id != user.id:
        membership = await db.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user.id,
            )
        )
        if membership is None or membership.role not in {"owner", "editor"}:
            raise HTTPException(status_code=403, detail="Project edit access required")
    run = await db.get(Run, payload.run_id)
    if run is None or run.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Owned run not found")
    if await db.get(RunProject, (run.id, project.id)) is None:
        db.add(RunProject(run_id=run.id, project_id=project.id))
        await db.commit()


@router.post("/{project_id}/runs/batch", response_model=ProjectRunBatchResult)
async def add_runs_batch(
    project_id: uuid.UUID,
    payload: ProjectRunBatchAdd,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectRunBatchResult:
    project = await accessible_project(db, user, project_id)
    if project.owner_id != user.id:
        membership = await db.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user.id,
                ProjectMembership.role.in_({"owner", "editor"}),
            )
        )
        if membership is None:
            raise HTTPException(status_code=403, detail="Project edit access required")

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
    db.add_all(RunProject(run_id=run_id, project_id=project.id) for run_id in new_ids)
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
    return [run_read(run) for run in runs]


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
