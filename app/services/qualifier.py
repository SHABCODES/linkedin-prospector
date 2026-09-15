"""
app/services/qualifier.py
Scores each LinkedIn prospect against a configurable ICP using Google Gemini.
Falls back to a rules-based scorer when GEMINI_API_KEY is not set.
"""
import json
import re
from typing import Any

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

# ── Default ICP (overridable at call time) ─────────────────────────────────────
DEFAULT_ICP = """
- Seniority: VP, Director, Head of, C-level
- Function: Sales, GTM, Growth, Revenue, Business Development
- Company stage: Series A, Series B, Series C, or scaling startup
- Industry preference: SaaS, Fintech, B2B Tech, HRTech, EdTech
- Geography: India preferred, but global is acceptable
- Company size: 50–2000 employees
"""


# ── Public interface ────────────────────────────────────────────────────────────

async def qualify_prospect(
    enriched: dict[str, Any],
    icp_description: str = DEFAULT_ICP,
) -> dict[str, Any]:
    """
    Score a prospect against the ICP.

    Returns:
        {
            "score": float,       # 0.0 – 1.0 (deterministic)
            "classification": str,# "High Fit" | "Review" | "Nurture" | "Reject"
            "reasons": list[str], # Explainable AI reasons
            "risks": list[str]    # Explainable AI risks
        }
    """
    score, classification = calculate_deterministic_score(enriched)
    
    if settings.llm_enabled:
        return await _gemini_qualify(enriched, icp_description, score, classification)
    return _rules_qualify(enriched, score, classification)


# ── Gemini qualifier ────────────────────────────────────────────────────────────

async def _gemini_qualify(enriched: dict, icp_description: str, score: float, classification: str) -> dict[str, Any]:
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(settings.gemini_model)

    prompt = f"""You are a GTM analyst qualifying a LinkedIn prospect.
We have already calculated a deterministic ICP score of {int(score*100)}/100 ({classification}).

ICP CRITERIA:
{icp_description}

PROSPECT PROFILE:
- Name: {enriched.get('full_name')}
- Headline: {enriched.get('headline')}
- Current Title: {enriched.get('current_title')}
- Current Company: {enriched.get('current_company')}
- Location: {enriched.get('location')}
- Industry: {enriched.get('industry')}
- Tenure in current role: {enriched.get('tenure_months')} months
- Recent role change: {enriched.get('role_change_detected')}
- Recent post/activity: {enriched.get('recent_post_snippet') or 'None available'}
- Education: {json.dumps(enriched.get('education')) if enriched.get('education') else 'None'}

Provide qualitative reasoning for why this prospect is or isn't a good fit, and identify any risks (missing info, red flags).

Respond with ONLY valid JSON in this exact format:
{{
  "reasons": ["<reason 1>", "<reason 2>"],
  "risks": ["<risk 1>", "<risk 2>"]
}}
"""

    log.info("qualifier.gemini_request", name=enriched.get("full_name"))
    response = model.generate_content(prompt)
    text = response.text.strip()

    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        result = json.loads(text)
    except Exception as e:
        log.error("qualifier.gemini_parse_error", error=str(e), text=text)
        result = {"reasons": ["LLM reasoning parse failed."], "risks": []}

    log.info(
        "qualifier.gemini_result",
        name=enriched.get("full_name"),
        score=score,
    )
    return {
        "score": score,
        "classification": classification,
        "reasons": result.get("reasons", []),
        "risks": result.get("risks", [])
    }


# ── Rules-based fallback ────────────────────────────────────────────────────────

_SENIOR_TITLES = {
    "vp", "vice president", "director", "head of", "chief", "cto", "cso", "cmo",
    "coo", "ceo", "president", "founder", "co-founder", "gm", "general manager",
}

_GTM_KEYWORDS = {
    "sales", "gtm", "growth", "revenue", "business development", "marketing",
    "partnerships", "channel", "account", "commercial",
}

_GOOD_INDUSTRIES = {
    "software", "saas", "fintech", "financial technology", "technology",
    "b2b", "hrtech", "edtech", "cloud", "ai",
}


def calculate_deterministic_score(enriched: dict) -> tuple[float, str]:
    """
    Calculate ICP score deterministically based on weighted criteria:
    Industry (20%), Company Size (20%), Role (20%), Technology (15%), Location (10%), Hiring Signal (15%)
    """
    score = 0.0
    
    headline = (enriched.get("headline") or "").lower()
    title = (enriched.get("current_title") or "").lower()
    industry = (enriched.get("industry") or "").lower()
    location = (enriched.get("location") or "").lower()
    
    # Industry (20%)
    if any(ind in industry for ind in _GOOD_INDUSTRIES):
        score += 0.20
        
    # Role (20%)
    if any(t in headline or t in title for t in _SENIOR_TITLES) and any(kw in headline or kw in title for kw in _GTM_KEYWORDS):
        score += 0.20
    elif any(t in headline or t in title for t in _SENIOR_TITLES) or any(kw in headline or kw in title for kw in _GTM_KEYWORDS):
        score += 0.10
        
    # Location (10%)
    if "india" in location or "in" == location:
        score += 0.10
        
    # Hiring Signal / Buying Trigger (15%)
    if enriched.get("role_change_detected"):
        score += 0.15
        
    # Company Size / Technology (35%)
    # Approximated through education/tenure/activity since we lack full firmographics in Proxycurl without extra enrichment
    if enriched.get("recent_post_snippet"):
        score += 0.15 # proxy for activity/technology usage
    if enriched.get("tenure_months", 0) > 12:
        score += 0.10
    if enriched.get("education"):
        score += 0.10

    score = min(score, 1.0)
    
    # 90-100 -> High priority
    # 70-89 -> Review
    # 50-69 -> Nurture
    # <50 -> Reject
    if score >= 0.90:
        classification = "High Fit"
    elif score >= 0.70:
        classification = "Review"
    elif score >= 0.50:
        classification = "Nurture"
    else:
        classification = "Reject"
        
    return round(score, 2), classification

def _rules_qualify(enriched: dict, score: float, classification: str) -> dict[str, Any]:
    """Heuristic scoring fallback when no LLM key is available."""
    reasons = [f"Deterministic score calculated as {int(score*100)}/100."]
    if score >= 0.70:
        reasons.append("Strong alignment with core ICP criteria.")
    else:
        reasons.append("Missing key ICP signals.")
        
    return {
        "score": score,
        "classification": classification,
        "reasons": reasons,
        "risks": ["LLM disabled; deep qualitative reasoning unavailable."],
    }
