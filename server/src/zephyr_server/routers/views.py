from __future__ import annotations

import uuid
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..dependencies import current_user
from ..models import ComparisonView, PlotRecipe, Project, ProjectMembership, User
from ..schemas import ComparisonViewWrite, PlotRecipeWrite, SavedViewRead

router = APIRouter(tags=["results explorer"])
Saved = TypeVar("Saved", PlotRecipe, ComparisonView)


async def list_saved(db: AsyncSession, user: User, model: type[Saved]) -> list[Saved]:
    accessible_projects = select(Project.id).where(
        or_(
            Project.owner_id == user.id,
            Project.visibility.in_({"group", "public"}),
            Project.id.in_(
                select(ProjectMembership.project_id).where(ProjectMembership.user_id == user.id)
            ),
        )
    )
    return list(
        await db.scalars(
            select(model)
            .where(or_(model.owner_id == user.id, model.project_id.in_(accessible_projects)))
            .order_by(model.updated_at.desc())
        )
    )


async def require_project_editor(
    db: AsyncSession, user: User, project_id: uuid.UUID | None
) -> None:
    if project_id is None:
        return
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id == user.id:
        return
    membership = await db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == user.id,
            ProjectMembership.role == "editor",
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Project edit access required")


@router.get("/plot-recipes", response_model=list[SavedViewRead])
async def plot_recipes(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await list_saved(db, user, PlotRecipe)


@router.post("/plot-recipes", response_model=SavedViewRead, status_code=status.HTTP_201_CREATED)
async def create_plot_recipe(
    payload: PlotRecipeWrite,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_editor(db, user, payload.project_id)
    record = PlotRecipe(owner_id=user.id, **payload.model_dump())
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.get("/comparison-views", response_model=list[SavedViewRead])
async def comparison_views(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await list_saved(db, user, ComparisonView)


@router.post("/comparison-views", response_model=SavedViewRead, status_code=status.HTTP_201_CREATED)
async def create_comparison_view(
    payload: ComparisonViewWrite,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_editor(db, user, payload.project_id)
    record = ComparisonView(owner_id=user.id, **payload.model_dump())
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.delete("/comparison-views/{view_id}", status_code=204)
async def delete_comparison_view(
    view_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(ComparisonView, view_id)
    if record is None or record.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Comparison view not found")
    await db.delete(record)
    await db.commit()
