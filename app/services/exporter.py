"""
app/services/exporter.py
Export prospects to CSV or push into the Project 1 (ai-outreach-engine) database.
"""
import csv
import io
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.linkedin_prospect import LinkedInProspect, ProspectOutreachDraft

log = structlog.get_logger(__name__)
settings = get_settings()


# ── CSV export ─────────────────────────────────────────────────────────────────

async def prospects_to_csv(
    prospects: list[LinkedInProspect],
    drafts_map: dict[str, ProspectOutreachDraft | None],
) -> str:
    """
    Serialise a list of prospects + their outreach drafts to CSV string.

    Args:
        prospects:  ORM objects
        drafts_map: {prospect_id: ProspectOutreachDraft | None}

    Returns:
        CSV string (UTF-8)
    """
    output = io.StringIO()
    fieldnames = [
        "full_name",
        "linkedin_url",
        "current_title",
        "current_company",
        "location",
        "industry",
        "fit_score",
        "fit_label",
        "fit_reasoning",
        "recent_post_snippet",
        "role_change_detected",
        "tenure_months",
        "status",
        "connection_note",
        "followup_dm",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for p in prospects:
        draft = drafts_map.get(p.id)
        writer.writerow({
            "full_name": p.full_name or "",
            "linkedin_url": p.linkedin_url,
            "current_title": p.current_title or "",
            "current_company": p.current_company or "",
            "location": p.location or "",
            "industry": p.industry or "",
            "fit_score": p.fit_score or "",
            "fit_label": p.fit_label or "",
            "fit_reasoning": p.fit_reasoning or "",
            "recent_post_snippet": (p.recent_post_snippet or "")[:100],
            "role_change_detected": p.role_change_detected,
            "tenure_months": p.tenure_months or "",
            "status": p.status,
            "connection_note": draft.connection_note if draft else "",
            "followup_dm": draft.followup_dm if draft else "",
        })

    return output.getvalue()


# ── CRM push (Project 1 integration) ───────────────────────────────────────────

async def push_to_outreach_engine(
    prospects: list[LinkedInProspect],
    drafts_map: dict[str, ProspectOutreachDraft | None],
) -> dict[str, Any]:
    """
    Push approved prospects into the ai-outreach-engine Postgres DB
    (Project 1 CRM store).

    Inserts into: prospects, contacts, activities tables.
    Safe to call multiple times — uses INSERT OR IGNORE / ON CONFLICT DO NOTHING.

    Returns:
        {"inserted": int, "skipped": int, "errors": list[str]}
    """
    if not settings.outreach_engine_db_url:
        raise ValueError(
            "OUTREACH_ENGINE_DB_URL is not configured. "
            "Set it in .env to enable CRM push."
        )

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    # Build a separate engine pointing at Project 1's DB
    outreach_engine = create_async_engine(settings.outreach_engine_db_url)
    OutreachSession = async_sessionmaker(bind=outreach_engine, expire_on_commit=False)

    inserted = 0
    skipped = 0
    errors: list[str] = []

    async with OutreachSession() as session:
        for p in prospects:
            try:
                # Upsert into prospects table (Project 1 schema)
                prospect_id = str(uuid.uuid4())
                await session.execute(
                    text("""
                    INSERT INTO prospects
                        (id, company_name, website, linkedin_url, industry, status, created_at)
                    VALUES
                        (:id, :company_name, :website, :linkedin_url, :industry, 'new', NOW())
                    ON CONFLICT (linkedin_url) DO NOTHING
                    """),
                    {
                        "id": prospect_id,
                        "company_name": p.current_company or "Unknown",
                        "website": None,
                        "linkedin_url": p.linkedin_url,
                        "industry": p.industry,
                    },
                )

                # Insert into contacts table
                draft = drafts_map.get(p.id)
                await session.execute(
                    text("""
                    INSERT INTO contacts
                        (id, prospect_id, name, linkedin_url, title)
                    VALUES
                        (:id, (SELECT id FROM prospects WHERE linkedin_url = :linkedin_url LIMIT 1),
                         :name, :linkedin_url, :title)
                    ON CONFLICT DO NOTHING
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "linkedin_url": p.linkedin_url,
                        "name": p.full_name or "Unknown",
                        "title": p.current_title,
                    },
                )

                # Insert approved outreach draft as an activity
                if draft and draft.connection_note:
                    await session.execute(
                        text("""
                        INSERT INTO activities
                            (id, contact_id, type, subject, body, sequence_step)
                        SELECT
                            :id,
                            c.id,
                            'linkedin_note',
                            'LinkedIn Connection Request',
                            :body,
                            1
                        FROM contacts c WHERE c.linkedin_url = :linkedin_url LIMIT 1
                        ON CONFLICT DO NOTHING
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "linkedin_url": p.linkedin_url,
                            "body": draft.connection_note,
                        },
                    )

                await session.commit()
                inserted += 1
                log.info("exporter.crm_push_ok", name=p.full_name)

            except Exception as exc:
                await session.rollback()
                errors.append(f"{p.full_name}: {exc}")
                skipped += 1
                log.error("exporter.crm_push_error", name=p.full_name, error=str(exc))

    await outreach_engine.dispose()
    
    # Push to HubSpot as well
    from app.services.hubspot import push_to_hubspot
    hs_result = await push_to_hubspot(prospects, drafts_map)
    
    return {
        "inserted": inserted, 
        "skipped": skipped, 
        "errors": errors,
        "hubspot": hs_result
    }
