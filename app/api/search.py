"""
app/api/search.py
POST /search — Trigger the full discovery → enrich → qualify → personalise pipeline.
"""
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.linkedin_prospect import LinkedInProspect, ProspectOutreachDraft, ProspectStatus
from app.models.pipeline_run import PipelineRun
from app.services import discovery, enricher, qualifier, personalizer

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=3, example="VP Sales at Series B SaaS companies, India")
    max_results: int = Field(default=10, ge=1, le=25)
    country: str = Field(default="IN", max_length=2)
    icp_description: str | None = Field(
        default=None,
        description="Custom ICP definition. Leave blank to use the default.",
    )


class SearchResponse(BaseModel):
    message: str
    total_found: int
    inserted: int
    skipped_duplicates: int
    prospects: list[dict[str, Any]]


@router.post("", response_model=SearchResponse)
async def run_search(req: SearchRequest, db: AsyncSession = Depends(get_db)):
    """
    Run the full LinkedIn prospecting pipeline:
    1. Discover profiles matching the query
    2. Enrich each profile
    3. Qualify against ICP
    4. Generate personalised outreach copy
    5. Persist to DB
    """
    log.info("search.start", query=req.query, max_results=req.max_results)

    # Initialize observability tracking
    import time
    from datetime import datetime, timezone
    
    pipeline_run = PipelineRun(
        search_query=req.query,
    )
    db.add(pipeline_run)
    await db.flush() # get ID
    
    start_time = time.time()

    # ── Step 1: Discover ──────────────────────────────────────────────────────
    raw_profiles = await discovery.discover_prospects(
        query=req.query,
        max_results=req.max_results,
        country=req.country,
    )

    if not raw_profiles:
        pipeline_run.completed_at = datetime.now(timezone.utc)
        pipeline_run.duration_seconds = time.time() - start_time
        await db.commit()
        raise HTTPException(status_code=404, detail="No profiles found for this query.")
        
    pipeline_run.total_discovered = len(raw_profiles)

    log.info("search.discovered", count=len(raw_profiles))

    # ── Steps 2-4: Enrich + Qualify + Personalise (sequential per profile) ───
    inserted = 0
    skipped = 0
    prospect_dicts = []

    for raw in raw_profiles:
        try:
            result = await _process_profile(raw, req.query, req.icp_description, db)
            if result is None:
                skipped += 1  # duplicate
                pipeline_run.skipped_duplicates += 1
            else:
                if result.get("status") == ProspectStatus.ENRICHMENT_FAILED.value:
                    pipeline_run.enrichment_failures += 1
                elif result.get("status") == ProspectStatus.LLM_FAILED.value:
                    pipeline_run.llm_failures += 1
                else:
                    inserted += 1
                    pipeline_run.successfully_processed += 1
                prospect_dicts.append(result)
        except Exception as exc:
            log.error("search.profile_error", error=str(exc))
            skipped += 1
            pipeline_run.enrichment_failures += 1 # generic failure fallback

    pipeline_run.completed_at = datetime.now(timezone.utc)
    pipeline_run.duration_seconds = time.time() - start_time
    await db.commit()

    log.info("search.complete", inserted=inserted, skipped=skipped)

    return SearchResponse(
        message=f"Pipeline complete. {inserted} prospects successfully processed.",
        total_found=len(raw_profiles),
        inserted=inserted,
        skipped_duplicates=skipped,
        prospects=prospect_dicts,
    )


async def _process_profile(
    raw: dict,
    search_query: str,
    icp_description: str | None,
    db: AsyncSession,
) -> dict | None:
    """Enrich → Qualify → Personalise → Persist one profile. Returns None if duplicate."""
    from datetime import datetime, timezone

    # ── Deduplication (Before Enrichment) ──
    # Proxycurl search returns 'profile_url' or 'linkedin_profile_url'. Mock returns 'linkedin_url'.
    linkedin_url = raw.get("linkedin_profile_url") or raw.get("profile_url") or raw.get("linkedin_url") or ""
    
    if not linkedin_url:
        log.warning("search.skip_no_url")
        return None

    existing_result = await db.execute(
        select(LinkedInProspect).where(LinkedInProspect.linkedin_url == linkedin_url)
    )
    existing = existing_result.scalar_one_or_none()
    
    if existing:
        log.info("search.skip_duplicate", url=linkedin_url)
        existing.last_seen = datetime.now(timezone.utc)
        sources = existing.discovery_sources or []
        if search_query not in sources:
            sources.append(search_query)
        existing.discovery_sources = sources
        await db.commit()
        
        # Fetch draft to return to UI
        draft_result = await db.execute(select(ProspectOutreachDraft).where(ProspectOutreachDraft.prospect_id == existing.id))
        draft = draft_result.scalar_one_or_none()
        
        res = existing.to_dict()
        res["outreach_draft"] = draft.to_dict() if draft else {}
        return res

    # ── Enrich ──
    try:
        enriched = await enricher.enrich_profile(raw)
        # Just in case enricher normalises the URL
        linkedin_url = enriched.get("linkedin_url") or linkedin_url 
    except Exception as e:
        log.error("search.enrichment_failed", error=str(e), url=linkedin_url)
        prospect = LinkedInProspect(
            linkedin_url=linkedin_url,
            status=ProspectStatus.ENRICHMENT_FAILED,
            search_query=search_query,
            discovery_sources=[search_query]
        )
        db.add(prospect)
        await db.flush()
        return prospect.to_dict()

    # ── Qualify ──
    try:
        qual = await qualifier.qualify_prospect(
            enriched,
            icp_description=icp_description or qualifier.DEFAULT_ICP,
        )
    except Exception as e:
        log.error("search.llm_failed", step="qualify", error=str(e), url=linkedin_url)
        prospect = LinkedInProspect(
            **{k: v for k, v in enriched.items() if k != "raw_profile" and k in LinkedInProspect.__table__.columns},
            raw_profile=enriched.get("raw_profile"),
            status=ProspectStatus.LLM_FAILED,
            search_query=search_query,
            discovery_sources=[search_query]
        )
        db.add(prospect)
        await db.flush()
        return prospect.to_dict()

    # ── Personalise ──
    try:
        copy = await personalizer.generate_outreach(enriched)
    except Exception as e:
        log.error("search.llm_failed", step="personalise", error=str(e), url=linkedin_url)
        raw_class = qual.get("classification") or qual.get("fit_label", "weak")
        fit_label = "strong" if raw_class == "High Fit" else "possible" if raw_class == "Review" else "weak"
        
        prospect = LinkedInProspect(
            **{k: v for k, v in enriched.items() if k != "raw_profile" and k in LinkedInProspect.__table__.columns},
            raw_profile=enriched.get("raw_profile"),
            fit_score=qual.get("score") or qual.get("fit_score"),
            fit_label=fit_label,
            reasons=qual.get("reasons", []),
            risks=qual.get("risks", []),
            status=ProspectStatus.LLM_FAILED,
            search_query=search_query,
            discovery_sources=[search_query]
        )
        db.add(prospect)
        await db.flush()
        return prospect.to_dict()

    # ── Persist prospect ──
    raw_class = qual.get("classification") or qual.get("fit_label", "weak")
    fit_label = "strong" if raw_class == "High Fit" else "possible" if raw_class == "Review" else "weak"
    
    prospect = LinkedInProspect(
        **{k: v for k, v in enriched.items() if k != "raw_profile" and k in LinkedInProspect.__table__.columns},
        raw_profile=enriched.get("raw_profile"),
        fit_score=qual.get("score") or qual.get("fit_score"),
        fit_label=fit_label,
        reasons=qual.get("reasons", []),
        risks=qual.get("risks", []),
        search_query=search_query,
        discovery_sources=[search_query],
        status=ProspectStatus.DRAFTED,  # Set to DRAFTED explicitly
    )
    db.add(prospect)
    await db.flush()  # get the ID

    # ── Persist outreach draft ──
    draft = ProspectOutreachDraft(
        prospect_id=prospect.id,
        connection_note=copy.get("connection_note"),
        followup_dm=copy.get("followup_dm"),
    )
    db.add(draft)

    result = prospect.to_dict()
    result["outreach_draft"] = draft.to_dict()
    return result
