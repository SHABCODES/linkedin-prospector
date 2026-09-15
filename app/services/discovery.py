"""
app/services/discovery.py
LinkedIn prospect discovery via Proxycurl People Search API.
Falls back to mock fixture data when PROXYCURL_API_KEY is not set.
"""
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/search"
MOCK_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "mock_profiles.json"


# ── Public interface ────────────────────────────────────────────────────────────

async def discover_prospects(
    query: str,
    max_results: int = 10,
    country: str = "IN",
) -> list[dict[str, Any]]:
    """
    Main entry point. Returns a list of raw Proxycurl profile dicts.

    Args:
        query:       Natural-language search string, e.g. "VP Sales at Series B SaaS, India"
        max_results: Maximum profiles to return (Proxycurl caps at 10/request by default)
        country:     ISO 3166-1 alpha-2 country filter (default: India)

    Returns:
        List of raw profile dicts (Proxycurl shape)
    """
    if settings.mock_mode:
        return await _mock_discover(query, max_results)
    return await _apollo_discover(query, max_results, country)


# ── Mock implementation ─────────────────────────────────────────────────────────

async def _mock_discover(query: str, max_results: int) -> list[dict[str, Any]]:
    """Return fixture profiles — no network calls, no cost."""
    log.info("discovery.mock_mode", query=query, max_results=max_results)
    with open(MOCK_DATA_PATH, encoding="utf-8") as f:
        profiles: list[dict] = json.load(f)

    # Simple keyword filter on headline/summary so different queries return
    # slightly different subsets, making the demo more convincing.
    keywords = [kw.lower() for kw in query.split() if len(kw) > 3]
    scored: list[tuple[int, dict]] = []
    for profile in profiles:
        text = (
            (profile.get("headline") or "") + " " + (profile.get("summary") or "")
        ).lower()
        hits = sum(1 for kw in keywords if kw in text)
        scored.append((hits, profile))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [p for _, p in scored[:max_results]]

    log.info("discovery.mock_results", count=len(results))
    return results


# ── Apollo implementation ───────────────────────────────────────────────────────

async def _apollo_discover(
    query: str, max_results: int, country: str
) -> list[dict[str, Any]]:
    """
    Call Apollo.io People Search API.
    
    We parse the natural language query heuristically:
    Everything before 'at' is treated as title filters, the rest as general keywords.
    """
    parts = query.split(" at ", maxsplit=1)
    title_filter = parts[0].strip() if len(parts) > 1 else None
    keyword_filter = parts[1].strip() if len(parts) > 1 else query.strip()

    payload: dict[str, Any] = {
        "per_page": min(max_results, 10),  # Apollo page size limit
    }
    
    if title_filter:
        payload["person_titles"] = [title_filter]
    if keyword_filter:
        payload["q_keywords"] = keyword_filter
        
    # We could add country filtering with `person_locations` but let's keep it simple for now

    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "X-Api-Key": settings.apollo_api_key
    }

    log.info("discovery.apollo_search", payload=payload)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(APOLLO_SEARCH_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("contacts", [])
    # If using mixed_people/search, it returns a list of contacts.
    log.info("discovery.apollo_results", count=len(results))
    return results

