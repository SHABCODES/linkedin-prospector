"""
app/api/metrics.py
Endpoints for exposing observability metrics.
"""
from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.pipeline_run import PipelineRun
from app.models.linkedin_prospect import LinkedInProspect

router = APIRouter(prefix="/metrics", tags=["metrics"])

@router.get("")
async def get_metrics(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Retrieve observability metrics for the system."""
    
    # Get last 10 pipeline runs
    runs_result = await db.execute(select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(10))
    runs = [run.to_dict() for run in runs_result.scalars().all()]
    
    # Get aggregate prospect stats
    status_counts_result = await db.execute(
        select(LinkedInProspect.status, func.count(LinkedInProspect.id)).group_by(LinkedInProspect.status)
    )
    status_counts = {status: count for status, count in status_counts_result.all()}
    
    # Calculate some global stats
    total_runs = await db.execute(select(func.count(PipelineRun.id)))
    total_runs = total_runs.scalar_one()

    return {
        "status": "healthy",
        "global": {
            "total_pipeline_runs": total_runs,
            "prospect_funnel": status_counts,
        },
        "recent_runs": runs
    }
