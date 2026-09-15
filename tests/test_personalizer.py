"""
tests/test_personalizer.py
Unit tests for the personalizer service (template mode — no Gemini key required).
"""
import pytest

from app.services.personalizer import generate_outreach, _template_generate


@pytest.mark.asyncio
async def test_generate_outreach_returns_both_fields():
    """generate_outreach must return connection_note and followup_dm."""
    enriched = {
        "full_name": "Priya Menon",
        "current_title": "Director of GTM",
        "current_company": "Saaslabs",
        "headline": "Director of GTM | Series B SaaS | PLG",
        "industry": "Software Development",
        "recent_post_snippet": "We just crossed ₹10Cr ARR",
        "role_change_detected": False,
        "tenure_months": 10,
    }
    result = await generate_outreach(enriched)
    assert "connection_note" in result
    assert "followup_dm" in result
    assert isinstance(result["connection_note"], str)
    assert isinstance(result["followup_dm"], str)


@pytest.mark.asyncio
async def test_connection_note_under_300_chars():
    """LinkedIn hard limit: connection note must be ≤300 characters."""
    for prospect in [
        {"full_name": "Arjun Sharma", "current_title": "VP Sales", "current_company": "Groww",
         "headline": "VP Sales @ Groww", "industry": "Fintech",
         "recent_post_snippet": "Why most SaaS SDR teams are set up to fail — and what the top 1% do differently",
         "role_change_detected": False, "tenure_months": 15},
        {"full_name": "Meenakshi Pillai", "current_title": "Chief Sales Officer", "current_company": "Exotel",
         "headline": "Chief Sales Officer | Cloud Communications | CCaaS",
         "industry": "Telecommunications",
         "recent_post_snippet": "CCaaS is becoming a commodity",
         "role_change_detected": True, "tenure_months": 3},
    ]:
        result = await generate_outreach(prospect)
        note = result["connection_note"]
        assert len(note) <= 300, f"Connection note is {len(note)} chars (limit 300): {note}"


@pytest.mark.asyncio
async def test_personalization_uses_recent_post():
    """When a recent post is available, it should appear in the generated copy."""
    enriched = {
        "full_name": "Sneha Iyer",
        "current_title": "Head of Enterprise Sales",
        "current_company": "Whatfix",
        "headline": "Head of Enterprise Sales | ex-Salesforce",
        "industry": "Software",
        "recent_post_snippet": "Cold email open rate of 68%",
        "role_change_detected": False,
        "tenure_months": 9,
    }
    result = _template_generate(enriched)
    # The recent post snippet should be referenced in at least one of the fields
    combined = result["connection_note"] + result["followup_dm"]
    assert "68%" in combined or "Cold email" in combined or "open rate" in combined


@pytest.mark.asyncio
async def test_personalization_uses_role_change():
    """When role_change_detected=True and no post, copy should reference the new role."""
    enriched = {
        "full_name": "Aditya Bose",
        "current_title": "Head of Growth",
        "current_company": "Zomentum",
        "headline": "Head of Growth @ Zomentum",
        "industry": "Software",
        "recent_post_snippet": None,
        "role_change_detected": True,
        "tenure_months": 2,
    }
    result = _template_generate(enriched)
    combined = result["connection_note"] + result["followup_dm"]
    # Should mention the company or role change
    assert "Zomentum" in combined or "Head of Growth" in combined or "join" in combined.lower()


@pytest.mark.asyncio
async def test_followup_dm_is_substantive():
    """Follow-up DM should be reasonably long (>100 chars)."""
    enriched = {
        "full_name": "Rahul Kapoor",
        "current_title": "CTO",
        "current_company": "PaySprint",
        "headline": "CTO @ PaySprint | YC W23",
        "industry": "Fintech",
        "recent_post_snippet": None,
        "role_change_detected": False,
        "tenure_months": 20,
    }
    result = await generate_outreach(enriched)
    assert len(result["followup_dm"]) > 100
