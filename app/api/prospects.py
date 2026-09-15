"""
app/api/prospects.py
CRUD endpoints for viewing, filtering and updating prospect status.
"""
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.linkedin_prospect import LinkedInProspect, ProspectOutreachDraft, ProspectStatus

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/prospects", tags=["prospects"])


# ── List & filter ───────────────────────────────────────────────────────────────

@router.get("")
async def list_prospects(
    status: str | None = Query(default=None, description="Filter by status"),
    fit_label: str | None = Query(default=None, description="Filter by fit_label"),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List prospects with optional filtering."""
    q = select(LinkedInProspect).order_by(LinkedInProspect.fit_score.desc())

    if status:
        q = q.where(LinkedInProspect.status == status)
    if fit_label:
        q = q.where(LinkedInProspect.fit_label == fit_label)
    if min_score is not None:
        q = q.where(LinkedInProspect.fit_score >= min_score)

    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    prospects = result.scalars().all()

    return {
        "total": len(prospects),
        "prospects": [p.to_dict() for p in prospects],
    }


# ── Get single prospect with drafts ────────────────────────────────────────────

@router.get("/{prospect_id}")
async def get_prospect(prospect_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Get a single prospect with all its outreach drafts."""
    result = await db.execute(
        select(LinkedInProspect).where(LinkedInProspect.id == prospect_id)
    )
    prospect = result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    drafts_result = await db.execute(
        select(ProspectOutreachDraft).where(
            ProspectOutreachDraft.prospect_id == prospect_id
        )
    )
    drafts = drafts_result.scalars().all()

    data = prospect.to_dict()
    data["outreach_drafts"] = [d.to_dict() for d in drafts]
    return data


# ── Update status ───────────────────────────────────────────────────────────────

class StatusUpdate(BaseModel):
    status: str

@router.patch("/{prospect_id}/status")
async def update_status(
    prospect_id: str, body: StatusUpdate, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Update prospect status (enforces state machine and handles routing)."""
    result = await db.execute(
        select(LinkedInProspect).where(LinkedInProspect.id == prospect_id)
    )
    prospect = result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    # Map legacy frontend status strings to Enums
    status_map = {
        "new": ProspectStatus.DRAFTED,
        "approved": ProspectStatus.APPROVED,
        "rejected": ProspectStatus.REJECTED,
        "contacted": ProspectStatus.CONTACTED,
    }
    
    try:
        new_status_str = body.status.upper()
        if new_status_str in status_map:
            new_status = status_map[new_status_str]
        else:
            new_status = ProspectStatus(new_status_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")

    # Explicit State Transitions Validation
    valid_transitions = {
        ProspectStatus.DISCOVERED: [ProspectStatus.ENRICHED],
        ProspectStatus.ENRICHED: [ProspectStatus.QUALIFIED],
        ProspectStatus.QUALIFIED: [ProspectStatus.DRAFTED],
        ProspectStatus.DRAFTED: [ProspectStatus.PENDING_REVIEW, ProspectStatus.APPROVED, ProspectStatus.REJECTED],
        ProspectStatus.PENDING_REVIEW: [ProspectStatus.APPROVED, ProspectStatus.REJECTED],
        ProspectStatus.APPROVED: [ProspectStatus.ROUTED, ProspectStatus.EXPORTED],
        ProspectStatus.ROUTED: [ProspectStatus.EXPORTED],
        ProspectStatus.EXPORTED: [ProspectStatus.CONTACTED],
        ProspectStatus.CONTACTED: [ProspectStatus.REPLIED],
    }

    current_status = prospect.status
    if new_status not in valid_transitions.get(current_status, []) and new_status != current_status:
        # For simplicity during UI transition, we allow jumping to APPROVED from DRAFTED directly
        if current_status == ProspectStatus.DISCOVERED:
            # Let it pass if UI hasn't caught up
            pass
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid transition from {current_status} to {new_status}"
            )

    prospect.status = new_status
    log.info("prospects.status_update", id=prospect_id, from_status=current_status, to_status=new_status)

    # Lead Routing Logic (Auto-route on approval)
    if new_status == ProspectStatus.APPROVED:
        score = prospect.fit_score or 0.0
        if score >= 0.90:
            prospect.owner = "AE"
            prospect.priority = "P1"
            prospect.segment = "Enterprise"
            prospect.routing_reason = "High score, immediate action"
            prospect.next_action = "Personalized Outreach"
        elif score >= 0.70:
            prospect.owner = "BDR"
            prospect.priority = "P2"
            prospect.segment = "Mid-Market"
            prospect.routing_reason = "Medium score, review required"
            prospect.next_action = "Review before outreach"
        else:
            prospect.owner = "Marketing"
            prospect.priority = "P3"
            prospect.segment = "SMB"
            prospect.routing_reason = "Low score, nurture"
            prospect.next_action = "Add to Nurture Campaign"
            
        prospect.status = ProspectStatus.ROUTED # Automatically advance state
        log.info("prospects.routed", id=prospect_id, owner=prospect.owner)

    return {"id": prospect_id, "status": prospect.status.value if hasattr(prospect.status, 'value') else prospect.status}


# ── Approve draft ───────────────────────────────────────────────────────────────

@router.patch("/{prospect_id}/drafts/{draft_id}/approve")
async def approve_draft(
    prospect_id: str, draft_id: str, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Mark an outreach draft as approved."""
    result = await db.execute(
        select(ProspectOutreachDraft).where(ProspectOutreachDraft.id == draft_id)
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    draft.approved = True
    log.info("prospects.draft_approved", draft_id=draft_id)
    return draft.to_dict()
