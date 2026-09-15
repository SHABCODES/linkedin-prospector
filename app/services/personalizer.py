"""
app/services/personalizer.py
Generates two pieces of outreach copy per prospect:
  1. connection_note  — LinkedIn connection request (≤300 chars, hard limit)
  2. followup_dm      — follow-up DM referencing a specific signal

Uses Google Gemini when available; falls back to template-based generation.
The key differentiator: copy references REAL signals (recent post, role change)
not generic merge fields.
"""
import re
from typing import Any

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()


# ── Public interface ────────────────────────────────────────────────────────────

async def generate_outreach(enriched: dict[str, Any]) -> dict[str, str]:
    """
    Generate personalised outreach copy for a prospect.

    Returns:
        {
            "connection_note": str,  # ≤300 chars
            "followup_dm": str       # 3–5 sentence follow-up
        }
    """
    if settings.llm_enabled:
        return await _gemini_generate(enriched)
    return _template_generate(enriched)


# ── Gemini generator ────────────────────────────────────────────────────────────

async def _gemini_generate(enriched: dict) -> dict[str, str]:
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(settings.gemini_model)

    # Build context string for the prompt
    recent_post = enriched.get("recent_post_snippet")
    role_changed = enriched.get("role_change_detected", False)
    tenure = enriched.get("tenure_months")

    signal_lines = []
    if recent_post:
        signal_lines.append(f'- Recent post/activity: "{recent_post}"')
    if role_changed and tenure is not None:
        signal_lines.append(
            f"- They recently started this role ({tenure} months ago) — potential buying trigger"
        )
    signals = "\n".join(signal_lines) if signal_lines else "- No specific signal available"

    prompt = f"""You are an expert B2B sales copywriter specialising in LinkedIn outreach.

Write TWO pieces of personalised outreach for this prospect. Your copy must:
- Reference a SPECIFIC detail from their profile (not generic praise)
- Sound human, not templated
- The connection note must be ≤300 characters (LinkedIn hard limit) — COUNT characters carefully

PROSPECT:
- Name: {enriched.get('full_name')}
- Title: {enriched.get('current_title')} at {enriched.get('current_company')}
- Headline: {enriched.get('headline')}
- Location: {enriched.get('location')}
- Industry: {enriched.get('industry')}

SIGNALS (use these to personalise):
{signals}

Respond with ONLY valid JSON in this exact format:
{{
  "connection_note": "<LinkedIn connection request — MUST be ≤300 characters, friendly, references a specific detail>",
  "followup_dm": "<Follow-up DM after they accept — 3 to 5 sentences, references their recent activity, asks a relevant question>"
}}
"""

    log.info("personalizer.gemini_request", name=enriched.get("full_name"))
    response = model.generate_content(prompt)
    text = response.text.strip()

    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    import json
    result = json.loads(text)

    # Enforce the 300-char limit as a hard constraint
    note = result.get("connection_note", "")
    if len(note) > 300:
        note = note[:297] + "..."
    result["connection_note"] = note

    log.info("personalizer.gemini_result", name=enriched.get("full_name"))
    return result


# ── Template fallback ───────────────────────────────────────────────────────────

def _template_generate(enriched: dict) -> dict[str, str]:
    """Deterministic template copy — used when no Gemini key is set."""
    name = (enriched.get("full_name") or "there").split()[0]
    title = enriched.get("current_title") or "your role"
    company = enriched.get("current_company") or "your company"
    recent_post = enriched.get("recent_post_snippet")
    role_changed = enriched.get("role_change_detected", False)

    # Pick the best personalisation hook
    if recent_post:
        hook = f'Your recent post on "{recent_post[:60]}..." really resonated.'
        dm_hook = f'I came across your post on "{recent_post[:80]}..." — great perspective.'
    elif role_changed:
        hook = f"Congrats on the new {title} role at {company}!"
        dm_hook = f"I noticed you recently joined {company} as {title} — congrats on the move!"
    else:
        hook = f"Your work as {title} at {company} caught my attention."
        dm_hook = f"I've been following what {company} is building in the {enriched.get('industry', 'tech')} space."

    connection_note = f"Hi {name}, {hook} I work with GTM and sales teams — would love to connect."
    # Trim to 300 chars
    if len(connection_note) > 300:
        connection_note = connection_note[:297] + "..."

    followup_dm = (
        f"Hi {name}, thanks for connecting! {dm_hook} "
        f"I'm currently helping {title.split()[0] if title else 'sales'} leaders at similar-stage "
        f"companies automate their prospecting and outreach workflows using AI — "
        f"cutting research time by 70%+ while keeping the copy genuinely personal. "
        f"Would a quick 20-minute chat to explore if there's a fit make sense?"
    )

    return {
        "connection_note": connection_note,
        "followup_dm": followup_dm,
    }
