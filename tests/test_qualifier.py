"""
tests/test_qualifier.py
Unit tests for the qualifier service (rules-based mode — no Gemini key required).
"""
import pytest

from app.services.qualifier import qualify_prospect, calculate_deterministic_score


@pytest.mark.asyncio
async def test_strong_fit_vp_sales():
    """A VP Sales at a SaaS company should score as 'strong'."""
    enriched = {
        "full_name": "Arjun Sharma",
        "headline": "VP Sales @ Series B SaaS | India",
        "current_title": "VP Sales",
        "current_company": "TechCorp",
        "location": "Bengaluru, India",
        "industry": "Software Development",
        "tenure_months": 24,
        "role_change_detected": False,
        "recent_post_snippet": "Why outbound is not dead",
    }
    result = await qualify_prospect(enriched)
    assert result["classification"] in ("High Fit", "Review")
    assert result["score"] >= 0.70
    assert isinstance(result["reasons"], list)
    assert len(result["reasons"]) > 0


@pytest.mark.asyncio
async def test_weak_fit_individual_contributor():
    """A junior IC in a non-GTM role should score as 'weak'."""
    enriched = {
        "full_name": "Test User",
        "headline": "Software Developer at Small Co",
        "current_title": "Junior Developer",
        "current_company": "XYZ",
        "location": "Mumbai",
        "industry": "Manufacturing",
        "tenure_months": 24,
        "role_change_detected": False,
        "recent_post_snippet": None,
    }
    result = await qualify_prospect(enriched)
    assert result["classification"] == "Reject"
    assert result["score"] < 0.40


@pytest.mark.asyncio
async def test_role_change_boost():
    """Recent role change should increase score."""
    base = {
        "full_name": "Test",
        "headline": "Head of Sales",
        "current_title": "Head of Sales",
        "current_company": "SaasCo",
        "location": "Delhi",
        "industry": "Software Development",
        "tenure_months": 2,
        "recent_post_snippet": None,
    }
    base["role_change_detected"] = False
    score_no_change, _ = calculate_deterministic_score({**base})

    base["role_change_detected"] = True
    score_changed, _ = calculate_deterministic_score({**base})

    assert score_changed > score_no_change


@pytest.mark.asyncio
async def test_recent_post_boost():
    """Having a recent post should slightly increase score."""
    base = {
        "full_name": "Test",
        "headline": "Director of Revenue",
        "current_title": "Director of Revenue",
        "current_company": "SaasCo",
        "location": "Hyderabad",
        "industry": "Software",
        "tenure_months": 18,
        "role_change_detected": False,
    }
    score_no_post, _ = calculate_deterministic_score({**base, "recent_post_snippet": None})
    score_with_post, _ = calculate_deterministic_score({**base, "recent_post_snippet": "Why RevOps matters"})
    assert score_with_post > score_no_post


@pytest.mark.asyncio
async def test_fit_score_range():
    """fit_score must always be in [0.0, 1.0]."""
    extreme = {
        "full_name": "X",
        "headline": "CEO CTO CMO COO VP Director Head Sales GTM Growth Revenue SaaS Fintech",
        "current_title": "CEO",
        "current_company": "MegaCorp",
        "location": "India",
        "industry": "software development saas b2b fintech",
        "tenure_months": 1,
        "role_change_detected": True,
        "recent_post_snippet": "Great post",
    }
    score, _ = calculate_deterministic_score(extreme)
    assert 0.0 <= score <= 1.0
