"""Tests for AnueScraper CNYES EPS API integration."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from analysis_bot.services.anue_scraper import AnueScraper


@pytest.fixture
def scraper():
    return AnueScraper()


def _make_api_response(year=None):
    """Build a realistic CNYES API response."""
    y = year or datetime.now().year
    return {
        "statusCode": 200,
        "message": "OK",
        "data": [
            {
                "market": "TWS",
                "code": "2330",
                "financialYear": y + 1,
                "rateDate": f"{y}-04-25",
                "feHigh": 130.0,
                "feLow": 110.0,
                "feMean": 120.0,
                "feMedian": 121.0,
                "numEst": 40,
                "currency": "TWD",
            },
            {
                "market": "TWS",
                "code": "2330",
                "financialYear": y,
                "rateDate": f"{y}-04-25",
                "feHigh": 100.0,
                "feLow": 90.0,
                "feMean": 95.0,
                "feMedian": 96.0,
                "numEst": 42,
                "currency": "TWD",
            },
        ],
    }


def _mock_session(json_data, status=200):
    """Create a mock aiohttp session that returns json_data."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = AsyncMock()
    session.get = lambda *a, **kw: ctx
    return session


# ── _fetch_eps_from_api ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_eps_from_api_weighted(scraper):
    """API returns weighted EPS from current + next year median."""
    session = _mock_session(_make_api_response())
    result = await scraper._fetch_eps_from_api(session, "2330")

    assert result is not None
    assert result["est_eps"] is not None
    # Weighted between 96 (this year) and 121 (next year)
    assert 96 <= result["est_eps"] <= 121
    assert result["est_price"] is None
    assert "2330" in result["url"]
    assert result["date"] is not None


@pytest.mark.asyncio
async def test_fetch_eps_from_api_no_current_year(scraper):
    """API returns None when current year data is missing."""
    data = _make_api_response()
    # Remove current year entry
    data["data"] = [d for d in data["data"] if d["financialYear"] != datetime.now().year]
    session = _mock_session(data)
    result = await scraper._fetch_eps_from_api(session, "2330")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_eps_from_api_http_error(scraper):
    """API returns None on HTTP error."""
    session = _mock_session({}, status=500)
    result = await scraper._fetch_eps_from_api(session, "2330")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_eps_from_api_empty_data(scraper):
    """API returns None when data is empty."""
    session = _mock_session({"statusCode": 200, "data": []})
    result = await scraper._fetch_eps_from_api(session, "2330")
    assert result is None


# ── _fetch_all_from_api ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_all_from_api(scraper):
    """API returns per-year snapshots sorted by date desc."""
    session = _mock_session(_make_api_response())
    results = await scraper._fetch_all_from_api(session, "2330")

    assert len(results) == 2
    assert results[0]["est_eps"] == 121.0  # next year (feMedian)
    assert results[1]["est_eps"] == 96.0  # current year (feMedian)


@pytest.mark.asyncio
async def test_fetch_all_from_api_empty(scraper):
    """API returns empty list on error."""
    session = _mock_session({}, status=404)
    results = await scraper._fetch_all_from_api(session, "9999")
    assert results == []


# ── fetch_estimated_data (integration: API first, fallback) ──────────────


@pytest.mark.asyncio
async def test_fetch_estimated_data_prefers_api(scraper):
    """fetch_estimated_data uses API when available, skips Yahoo search."""
    api_result = {"est_price": None, "est_eps": 98.5, "url": "...", "date": "2026-04-25"}
    with patch.object(scraper, "_fetch_eps_from_api", return_value=api_result):
        with patch.object(scraper, "_fetch_eps_from_search") as mock_search:
            session = AsyncMock()
            result = await scraper.fetch_estimated_data(session, "2330", "台積電")
            assert result["est_eps"] == 98.5
            mock_search.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_estimated_data_falls_back_to_search(scraper):
    """fetch_estimated_data falls back to search when API fails."""
    search_result = {"est_price": 900.0, "est_eps": 95.0, "url": "...", "date": "2026-01-01"}
    with patch.object(scraper, "_fetch_eps_from_api", return_value=None):
        with patch.object(scraper, "_fetch_eps_from_search", return_value=search_result) as mock_s:
            session = AsyncMock()
            result = await scraper.fetch_estimated_data(session, "2330", "台積電")
            assert result["est_eps"] == 95.0
            mock_s.assert_called_once()
