"""
app/services/enricher.py
Enriches a raw Proxycurl profile dict into a structured dict
ready for database insertion.

In mock mode, raw profiles already contain the data; this service
normalises and computes derived fields (tenure_months, role_change_detected).
In live mode, it calls the Proxycurl Person API for any profile that
only has a linkedin_url (e.g. from search results returned with enrich=skip).
"""
from datetime import datetime
from typing import Any, Optional

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

PROXYCURL_PERSON_URL = "https://nubela.co/proxycurl/api/v2/linkedin"


# ── Public interface ────────────────────────────────────────────────────────────

async def enrich_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Accept a raw dict and return a normalised enrichment dict.
    """
    if settings.mock_mode:
        return _normalise_proxycurl(raw)
    else:
        # Apollo's search API already returns a rich contact object, so we don't 
        # necessarily need a second API call to enrich it. We just normalise it.
        return _normalise_apollo(raw)


# ── Normalisation (Branching) ───────────────────────────────────────────────────

def _normalise_proxycurl(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract and compute all fields we store from a raw Proxycurl profile (used for Mock)."""
    experiences: list[dict] = raw.get("experiences", []) or []
    current_exp = _current_experience_proxycurl(experiences)

    return {
        "linkedin_url": raw.get("linkedin_url") or raw.get("profile_url") or "",
        "full_name": raw.get("full_name") or _build_name_proxycurl(raw),
        "headline": raw.get("headline") or raw.get("occupation") or "",
        "current_title": current_exp.get("title") if current_exp else raw.get("occupation"),
        "current_company": current_exp.get("company") if current_exp else None,
        "location": raw.get("location") or raw.get("city"),
        "industry": raw.get("industry"),
        "tenure_months": _tenure_months_proxycurl(current_exp),
        "recent_post_snippet": _latest_post_proxycurl(raw),
        "role_change_detected": _role_changed_recently_proxycurl(experiences),
        "education": raw.get("education") or [],
        "raw_profile": raw,
    }

def _normalise_apollo(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract and compute fields from an Apollo.io contact payload."""
    employment_history = raw.get("employment_history") or []
    current_exp = None
    if employment_history:
        current_exp = employment_history[0]  # Usually sorted newest first

    org = raw.get("organization") or {}

    return {
        "linkedin_url": raw.get("linkedin_url") or "",
        "full_name": raw.get("name") or f"{raw.get('first_name','')} {raw.get('last_name','')}".strip(),
        "headline": raw.get("headline") or raw.get("title") or "",
        "current_title": raw.get("title") or (current_exp.get("title") if current_exp else None),
        "current_company": raw.get("organization_name") or (current_exp.get("organization_name") if current_exp else None),
        "location": raw.get("city") or raw.get("state") or raw.get("country"),
        "industry": org.get("industry") or raw.get("industry"),
        "tenure_months": _tenure_months_apollo(current_exp),
        "recent_post_snippet": None, # Apollo doesn't provide recent posts usually
        "role_change_detected": _role_changed_recently_apollo(employment_history),
        "education": [], # Apollo education is sometimes in `educational_history`
        "raw_profile": raw,
    }

# ── Proxycurl Helpers (for Mock) ────────────────────────────────────────────────

def _build_name_proxycurl(raw: dict) -> Optional[str]:
    first = raw.get("first_name", "")
    last = raw.get("last_name", "")
    return f"{first} {last}".strip() or None

def _current_experience_proxycurl(experiences: list[dict]) -> Optional[dict]:
    for exp in experiences:
        if exp.get("ends_at") is None:
            return exp
    return experiences[0] if experiences else None

def _tenure_months_proxycurl(exp: Optional[dict]) -> Optional[int]:
    if not exp:
        return None
    starts_at = exp.get("starts_at")
    if not starts_at:
        return None
    try:
        start = datetime(
            year=starts_at.get("year", 2020),
            month=starts_at.get("month", 1),
            day=starts_at.get("day", 1),
        )
        delta = datetime.now() - start
        return max(0, delta.days // 30)
    except Exception:
        return None

def _latest_post_proxycurl(raw: dict) -> Optional[str]:
    activities: list[dict] = raw.get("activities", []) or []
    if activities:
        return activities[0].get("title") or activities[0].get("description")
    return None

def _role_changed_recently_proxycurl(experiences: list[dict], threshold_months: int = 6) -> bool:
    current = _current_experience_proxycurl(experiences)
    if not current:
        return False
    tenure = _tenure_months_proxycurl(current)
    if tenure is None:
        return False
    return tenure <= threshold_months


# ── Apollo Helpers ─────────────────────────────────────────────────────────────

def _tenure_months_apollo(exp: Optional[dict]) -> Optional[int]:
    if not exp:
        return None
    # Apollo start_date is usually ISO "YYYY-MM-DD"
    start_str = exp.get("start_date")
    if not start_str:
        return None
    try:
        # naive parse
        year = int(start_str[0:4])
        month = int(start_str[5:7]) if len(start_str) >= 7 else 1
        start = datetime(year=year, month=month, day=1)
        delta = datetime.now() - start
        return max(0, delta.days // 30)
    except Exception:
        return None

def _role_changed_recently_apollo(experiences: list[dict], threshold_months: int = 6) -> bool:
    if not experiences:
        return False
    current = experiences[0]
    tenure = _tenure_months_apollo(current)
    if tenure is None:
        return False
    return tenure <= threshold_months
