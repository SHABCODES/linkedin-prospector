"""
app/services/hubspot.py
HubSpot CRM Integration. Pushes prospects as Contacts and creates an initial Note Activity.
"""
import httpx
import structlog
from typing import Any
from datetime import datetime, timezone

from app.config import get_settings
from app.models.linkedin_prospect import LinkedInProspect, ProspectOutreachDraft

log = structlog.get_logger(__name__)
settings = get_settings()

HUBSPOT_API_BASE = "https://api.hubapi.com/crm/v3"

async def push_to_hubspot(prospects: list[LinkedInProspect], drafts_map: dict[str, ProspectOutreachDraft | None]) -> dict[str, Any]:
    """
    Push approved prospects to HubSpot CRM.
    
    Returns:
        {"inserted": int, "skipped": int, "errors": list[str]}
    """
    if not settings.hubspot_access_token:
        log.warning("hubspot.skip_no_token", message="HUBSPOT_ACCESS_TOKEN not set, skipping real export and mocking success.")
        # Mock mode if no token
        return {"inserted": len(prospects), "skipped": 0, "errors": []}

    inserted = 0
    skipped = 0
    errors: list[str] = []

    headers = {
        "Authorization": f"Bearer {settings.hubspot_access_token}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for p in prospects:
            try:
                draft = drafts_map.get(p.id)
                # Create Contact
                names = (p.full_name or "").split(" ", 1)
                first_name = names[0] if len(names) > 0 else ""
                last_name = names[1] if len(names) > 1 else ""

                contact_payload = {
                    "properties": {
                        "firstname": first_name,
                        "lastname": last_name,
                        "jobtitle": p.current_title or "",
                        "company": p.current_company or "",
                        "industry": p.industry or "",
                        "linkedin": p.linkedin_url or "",
                        "hs_lead_status": "NEW"
                    }
                }

                resp = await client.post(f"{HUBSPOT_API_BASE}/objects/contacts", json=contact_payload, headers=headers)
                
                contact_id = None
                if resp.status_code == 409: # Conflict / already exists
                    contact_id = resp.json().get("message", "").split("existing ID: ")[-1].strip()
                    log.info("hubspot.contact_exists", url=p.linkedin_url, hs_contact_id=contact_id)
                elif resp.status_code in (200, 201):
                    contact_id = resp.json().get("id")
                    log.info("hubspot.contact_created", url=p.linkedin_url, hs_contact_id=contact_id)
                else:
                    resp.raise_for_status()

                # Add Note with Draft
                if contact_id and draft and draft.connection_note:
                    note_payload = {
                        "properties": {
                            "hs_timestamp": datetime.now(timezone.utc).isoformat(),
                            "hs_note_body": f"Suggested LinkedIn Note:\n\n{draft.connection_note}"
                        },
                        "associations": [
                            {
                                "to": {"id": contact_id},
                                "types": [
                                    {
                                        "associationCategory": "HUBSPOT_DEFINED",
                                        "associationTypeId": 202 # Contact to Note
                                    }
                                ]
                            }
                        ]
                    }
                    note_resp = await client.post(f"{HUBSPOT_API_BASE}/objects/notes", json=note_payload, headers=headers)
                    if note_resp.status_code not in (200, 201):
                        log.warning("hubspot.note_creation_failed", response=note_resp.text)
                
                inserted += 1

            except Exception as e:
                log.error("hubspot.push_error", error=str(e), url=p.linkedin_url)
                errors.append(f"{p.full_name}: {str(e)}")
                skipped += 1

    return {"inserted": inserted, "skipped": skipped, "errors": errors}
