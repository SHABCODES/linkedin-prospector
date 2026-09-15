"""
app/api/export.py
Export endpoints: CSV download and optional push to Project 1 CRM.
"""
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.linkedin_prospect import LinkedInProspect, ProspectOutreachDraft
from app.services.exporter import prospects_to_csv, push_to_outreach_engine

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/export", tags=["export"])


async def _get_prospects_and_drafts(
    db: AsyncSession,
    status: str | None,
    fit_label: str | None,
    min_score: float | None,
) -> tuple[list[LinkedInProspect], dict[str, ProspectOutreachDraft | None]]:
    """Shared query helper for both export endpoints."""
    q = select(LinkedInProspect).order_by(LinkedInProspect.fit_score.desc())

    if status:
        q = q.where(LinkedInProspect.status == status)
    if fit_label:
        q = q.where(LinkedInProspect.fit_label == fit_label)
    if min_score is not None:
        q = q.where(LinkedInProspect.fit_score >= min_score)

    result = await db.execute(q)
    prospects = result.scalars().all()

    # Fetch all matching drafts
    if prospects:
        prospect_ids = [p.id for p in prospects]
        drafts_result = await db.execute(
            select(ProspectOutreachDraft).where(
                ProspectOutreachDraft.prospect_id.in_(prospect_ids)
            )
        )
        drafts = drafts_result.scalars().all()
        # Map: prospect_id -> first draft (most recently generated)
        drafts_map: dict[str, ProspectOutreachDraft | None] = {}
        for d in drafts:
            if d.prospect_id not in drafts_map:
                drafts_map[d.prospect_id] = d
    else:
        drafts_map = {}

    return list(prospects), drafts_map


@router.get("/csv")
async def export_csv(
    status: str | None = Query(default=None),
    fit_label: str | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    """Download prospects + outreach drafts as a CSV file."""
    prospects, drafts_map = await _get_prospects_and_drafts(db, status, fit_label, min_score)

    if not prospects:
        raise HTTPException(status_code=404, detail="No prospects match the given filters.")

    csv_content = await prospects_to_csv(prospects, drafts_map)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=linkedin_prospects.csv"},
    )


@router.post("/crm")
async def export_to_crm(
    status: str | None = Query(default="approved"),
    fit_label: str | None = Query(default=None),
    min_score: float | None = Query(default=0.5, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Push approved prospects into the ai-outreach-engine CRM database."""
    prospects, drafts_map = await _get_prospects_and_drafts(db, status, fit_label, min_score)

    if not prospects:
        raise HTTPException(status_code=404, detail="No prospects match the given filters.")

    log.info("export.crm_push_start", count=len(prospects))
    result = await push_to_outreach_engine(prospects, drafts_map)
    log.info("export.crm_push_done", **result)
    return result
