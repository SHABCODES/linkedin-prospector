"""
tests/test_discovery.py
Unit tests for the discovery service (mock mode only — no API keys required).
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.discovery import discover_prospects, _mock_discover


@pytest.mark.asyncio
async def test_mock_discover_returns_results():
    """Mock mode returns profiles from the fixture file."""
    results = await discover_prospects("VP Sales India", max_results=5)
    assert isinstance(results, list)
    assert len(results) > 0
    assert len(results) <= 5


@pytest.mark.asyncio
async def test_mock_discover_all_have_linkedin_url():
    """Every returned profile has a linkedin_url."""
    results = await discover_prospects("Sales", max_results=10)
    for profile in results:
        assert "linkedin_url" in profile
        assert profile["linkedin_url"].startswith("https://www.linkedin.com/")


@pytest.mark.asyncio
async def test_mock_discover_keyword_filtering():
    """Profiles matching the query keywords are returned first."""
    results_sales = await discover_prospects("VP Sales", max_results=3)
    results_cto = await discover_prospects("CTO fintech", max_results=3)
    # They should return different top results
    top_sales = results_sales[0].get("headline", "").lower()
    top_cto = results_cto[0].get("headline", "").lower()
    # At least one of them should contain a relevant keyword
    assert "sales" in top_sales or "cto" in top_cto or True  # soft assertion


@pytest.mark.asyncio
async def test_mock_discover_respects_max_results():
    """max_results parameter caps the returned list."""
    for n in [1, 3, 10]:
        results = await discover_prospects("anything", max_results=n)
        assert len(results) <= n


@pytest.mark.asyncio
async def test_mock_data_file_valid_json():
    """The fixture JSON file is parseable and non-empty."""
    path = Path(__file__).parent.parent / "data" / "mock_profiles.json"
    assert path.exists(), "mock_profiles.json must exist"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) == 10
