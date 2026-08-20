from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db import get_db
from ..dependencies import current_user
from ..models import RunMetadata, ThermoSeries, User
from .runs import (
    artifact_previews_for_runs,
    copy_counts_for_runs,
    get_accessible_run,
    run_read,
)

router = APIRouter(prefix="/comparisons", tags=["results explorer"])


@router.get("/runs")
async def compare_runs(
    ids: list[uuid.UUID] = Query(min_length=2, max_length=20),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = []
    runs = [await get_accessible_run(db, user, run_id) for run_id in ids]
    previews = await artifact_previews_for_runs(db, runs)
    copy_counts = await copy_counts_for_runs(db, runs)
    for run in runs:
        metadata = await db.get(RunMetadata, run.id)
        series = list(
            await db.scalars(
                select(ThermoSeries)
                .where(ThermoSeries.run_id == run.id)
                .options(selectinload(ThermoSeries.points))
                .order_by(ThermoSeries.segment)
            )
        )
        result.append(
            {
                "run": run_read(
                    run,
                    *previews.get(run.id, (0, [])),
                    copy_count=copy_counts.get(run.id, 0),
                ),
                "metadata": metadata.values if metadata else {},
                "thermo": [
                    {
                        "segment": item.segment,
                        "columns": item.columns,
                        "rows": [
                            {"sequence": point.sequence, "values": point.values}
                            for point in item.points
                        ],
                    }
                    for item in series
                ],
            }
        )
    return {"runs": result}
