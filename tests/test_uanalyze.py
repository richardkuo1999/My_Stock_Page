"""Tests for tools/uanalyze.py."""

import asyncio
import json
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.uanalyze import (
    GIDP_TOKEN,
    WACC,
    DEFAULT_MULTI_CONCURRENCY,
    UAnalyzeAuth,
    _auth,
    _compute_dcf,
    _request_with_auth,
    analyze,
    analyze_multi,
    fetch_dcf_valuation,
    fetch_eps_consensus,
    fetch_cash_flow_trend,
    fetch_company_keywords,
    fetch_dividend_policy,
    fetch_ai_chat,
    fetch_holder_structure,
    fetch_institutional_chips,
    fetch_margin_trading,
    fetch_order_visibility,
    fetch_peers_comparison,
    fetch_per_share_metrics,
    fetch_profit_margins,
    fetch_supply_chain,
    fetch_transcript_detail,
    fetch_transcript_list,
    fetch_valuation_bands,
    get_completion,
    get_reports,
    list_latest_reports,
)


# --- Helpers ---


def _make_httpx_response(status_code: int, json_data: dict) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def _mock_async_client(response):
    """Build a mock httpx.AsyncClient that returns `response` on get()/post()."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.post = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.fixture(autouse=True)
def _reset_auth():
    """Reset module-level auth state between tests."""
    _auth.access_token = None
    _auth.refresh_token = None
    _auth.token_type = None
    _auth.expires_in = None
    yield
    _auth.access_token = None
    _auth.refresh_token = None
    _auth.token_type = None
    _auth.expires_in = None


# --- Login tests ---


@pytest.mark.asyncio
async def test_login_success():
    """Successful login stores tokens and returns True."""
    login_resp = _make_httpx_response(
        200, {"access_token": "tok123", "refresh_token": "ref456"}
    )
    mock_client = _mock_async_client(login_resp)

    auth = UAnalyzeAuth()
    with (
        patch.dict(
            "os.environ",
            {"UANALYZE_EMAIL": "a@b.com", "UANALYZE_PASSWORD": "pass"},
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await auth.login()

    assert result is True
    assert auth.access_token == "tok123"
    assert auth.refresh_token == "ref456"


@pytest.mark.asyncio
async def test_login_success_data_wrapped():
    """Real UAnalyze API wraps tokens under a 'data' key — parse that too."""
    login_resp = _make_httpx_response(
        200, {"data": {"access_token": "tokWrapped", "refresh_token": "refWrapped"}}
    )
    mock_client = _mock_async_client(login_resp)

    auth = UAnalyzeAuth()
    with (
        patch.dict(
            "os.environ",
            {"UANALYZE_EMAIL": "a@b.com", "UANALYZE_PASSWORD": "pass"},
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await auth.login()

    assert result is True
    assert auth.access_token == "tokWrapped"
    assert auth.refresh_token == "refWrapped"


@pytest.mark.asyncio
async def test_login_failure():
    """Login with bad credentials returns False."""
    login_resp = _make_httpx_response(401, {"error": "unauthorized"})
    mock_client = _mock_async_client(login_resp)

    auth = UAnalyzeAuth()
    with (
        patch.dict(
            "os.environ",
            {"UANALYZE_EMAIL": "a@b.com", "UANALYZE_PASSWORD": "bad"},
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await auth.login()

    assert result is False
    assert auth.access_token is None


@pytest.mark.asyncio
async def test_login_no_credentials():
    """Missing env vars → login returns False without making request."""
    auth = UAnalyzeAuth()
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await auth.login()

    assert result is False


# --- Refresh tests ---


@pytest.mark.asyncio
async def test_refresh_success():
    """Successful refresh updates access_token."""
    refresh_resp = _make_httpx_response(200, {"access_token": "newtok"})
    mock_client = _mock_async_client(refresh_resp)

    auth = UAnalyzeAuth()
    auth.refresh_token = "ref456"

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await auth.refresh()

    assert result is True
    assert auth.access_token == "newtok"


@pytest.mark.asyncio
async def test_refresh_failure():
    """No refresh_token → refresh returns False immediately."""
    auth = UAnalyzeAuth()
    auth.refresh_token = None
    result = await auth.refresh()
    assert result is False


@pytest.mark.asyncio
async def test_refresh_http_error():
    """Refresh endpoint returns non-200 → returns False."""
    refresh_resp = _make_httpx_response(403, {"error": "forbidden"})
    mock_client = _mock_async_client(refresh_resp)

    auth = UAnalyzeAuth()
    auth.refresh_token = "ref456"

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await auth.refresh()

    assert result is False


# --- Auth material assembly tests (Ticket 01) ---


@pytest.mark.asyncio
async def test_login_stores_token_type_and_expires_in():
    """Login stores all 4 fields (needed by cookie_context)."""
    login_resp = _make_httpx_response(
        200,
        {
            "access_token": "tok123",
            "refresh_token": "ref456",
            "token_type": "bearer",
            "expires_in": 3600,
        },
    )
    mock_client = _mock_async_client(login_resp)

    auth = UAnalyzeAuth()
    with (
        patch.dict(
            "os.environ",
            {"UANALYZE_EMAIL": "a@b.com", "UANALYZE_PASSWORD": "pass"},
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        result = await auth.login()

    assert result is True
    assert auth.token_type == "bearer"
    assert auth.expires_in == 3600


def test_jwt_headers():
    """jwt_headers() Authorization uses the access_token."""
    auth = UAnalyzeAuth()
    auth.access_token = "tok123"
    headers = auth.jwt_headers()
    assert headers["Authorization"] == "Bearer tok123"
    assert headers["Accept"] == "application/json"
    assert headers["Referer"] == "https://pro.uanalyze.com.tw/"


def test_cookie_context():
    """cookie_context() returns 4 cookies + Origin/Referer headers."""
    auth = UAnalyzeAuth()
    auth.access_token = "tok123"
    auth.refresh_token = "ref456"
    auth.token_type = "bearer"
    auth.expires_in = 3600

    cookies, headers = auth.cookie_context()

    assert set(cookies.keys()) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_in",
    }
    assert cookies["access_token"] == "tok123"
    assert cookies["expires_in"] == "3600"  # coerced to str
    assert headers["Origin"] == "https://pro.uanalyze.com.tw"
    assert headers["Referer"] == "https://pro.uanalyze.com.tw/"


def test_cookie_context_token_type_none():
    """token_type None → empty string in cookies."""
    auth = UAnalyzeAuth()
    auth.access_token = "tok123"
    auth.refresh_token = "ref456"
    auth.token_type = None
    auth.expires_in = 3600

    cookies, _ = auth.cookie_context()
    assert cookies["token_type"] == ""


def test_gidp_headers():
    """gidp_headers() uses the fixed GIDP token, not the access_token."""
    auth = UAnalyzeAuth()
    auth.access_token = "tok123"
    headers = auth.gidp_headers()
    assert headers["Authorization"] == f"Bearer {GIDP_TOKEN}"
    assert GIDP_TOKEN.startswith("tquEQ")
    assert "tok123" not in headers["Authorization"]


# --- analyze() tests ---

@pytest.mark.asyncio
async def test_analyze_success():
    """Full flow: login → completion → returns analysis dict."""
    login_resp = _make_httpx_response(
        200, {"access_token": "tok", "refresh_token": "ref"}
    )
    completion_resp = _make_httpx_response(
        200, {"data": {"text": "台積電近況分析..."}}
    )

    mock_login_client = AsyncMock()
    mock_login_client.post = AsyncMock(return_value=login_resp)
    mock_login_client.__aenter__ = AsyncMock(return_value=mock_login_client)
    mock_login_client.__aexit__ = AsyncMock(return_value=False)

    mock_api_client = AsyncMock()
    mock_api_client.get = AsyncMock(return_value=completion_resp)
    mock_api_client.__aenter__ = AsyncMock(return_value=mock_api_client)
    mock_api_client.__aexit__ = AsyncMock(return_value=False)

    clients = iter([mock_login_client, mock_api_client])

    with (
        patch.dict(
            "os.environ",
            {"UANALYZE_EMAIL": "a@b.com", "UANALYZE_PASSWORD": "pass"},
        ),
        patch("httpx.AsyncClient", side_effect=lambda **kwargs: next(clients)),
    ):
        result = await analyze("2330")

    assert result["analysis"] == "台積電近況分析..."
    assert result["symbol"] == "2330"
    assert result["prompt"] == "近況發展"


@pytest.mark.asyncio
async def test_analyze_auto_refresh():
    """First API call returns 401 → refresh → retry succeeds."""
    # Pre-set an expired token and refresh token on module auth
    _auth.access_token = "expired_tok"
    _auth.refresh_token = "ref456"

    first_resp = _make_httpx_response(401, {"error": "token expired"})
    refresh_resp = _make_httpx_response(200, {"access_token": "new_tok"})
    success_resp = _make_httpx_response(
        200, {"data": {"text": "refreshed result"}}
    )

    # The API client: first GET returns 401, second GET returns success
    mock_api_client = AsyncMock()
    mock_api_client.get = AsyncMock(side_effect=[first_resp, success_resp])
    mock_api_client.__aenter__ = AsyncMock(return_value=mock_api_client)
    mock_api_client.__aexit__ = AsyncMock(return_value=False)

    # The refresh client
    mock_refresh_client = AsyncMock()
    mock_refresh_client.post = AsyncMock(return_value=refresh_resp)
    mock_refresh_client.__aenter__ = AsyncMock(return_value=mock_refresh_client)
    mock_refresh_client.__aexit__ = AsyncMock(return_value=False)

    clients = iter([mock_api_client, mock_refresh_client])

    with (
        patch.dict(
            "os.environ",
            {"UANALYZE_EMAIL": "a@b.com", "UANALYZE_PASSWORD": "pass"},
        ),
        patch("httpx.AsyncClient", side_effect=lambda **kwargs: next(clients)),
    ):
        result = await get_completion("2330")

    assert result["analysis"] == "refreshed result"
    assert _auth.access_token == "new_tok"


@pytest.mark.asyncio
async def test_analyze_no_credentials():
    """Missing credentials → returns error dict."""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await analyze("2330")

    assert "error" in result
    assert "UANALYZE_EMAIL" in result["error"] or "UANALYZE_PASSWORD" in result["error"]


@pytest.mark.asyncio
async def test_analyze_empty_symbol():
    """Empty symbol → returns error."""
    with patch.dict(
        "os.environ",
        {"UANALYZE_EMAIL": "a@b.com", "UANALYZE_PASSWORD": "pass"},
    ):
        result = await analyze("  ")

    assert "error" in result
    assert "股票代號" in result["error"]


# --- get_reports() tests ---


@pytest.mark.asyncio
async def test_get_reports_success():
    """Report summaries are parsed correctly."""
    _auth.access_token = "tok"

    reports_data = {
        "data": [
            {
                "title": "Q3 報告",
                "summary": "營收成長 20%",
                "date": "2024-10-01",
                "url": "https://example.com/report1",
            },
            {
                "title": "Q2 報告",
                "summary": "毛利率改善",
                "date": "2024-07-01",
                "url": "https://example.com/report2",
            },
        ]
    }
    api_resp = _make_httpx_response(200, reports_data)
    mock_client = _mock_async_client(api_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await get_reports("2330")

    assert "reports" in result
    assert len(result["reports"]) == 2
    assert result["reports"][0]["title"] == "Q3 報告"
    assert result["reports"][1]["summary"] == "毛利率改善"
    assert result["symbol"] == "2330"


@pytest.mark.asyncio
async def test_get_reports_failure():
    """API returns non-200 → error dict."""
    _auth.access_token = "tok"

    api_resp = _make_httpx_response(500, {"error": "internal"})
    mock_client = _mock_async_client(api_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await get_reports("9999")

    assert "error" in result
    assert "9999" in result["error"]


# --- list_latest_reports() tests ---


@pytest.mark.asyncio
async def test_list_latest_reports_success():
    """Reports parsed with stock_code (name) / stock_name / title (question_type)."""
    _auth.access_token = "tok"

    reports_data = {
        "data": [
            {
                "id": 102,
                "name": "2330",
                "stock_name": "台積電",
                "question_type": "資本支出",
                "content_date": "2024-10-15 00:00:00",
                "summary": "毛利率創高",
            },
            {
                "id": 101,
                "name": "2454",
                "stock_name": "聯發科",
                "question_type": "近況發展",
                "content_date": "2024-10-14 00:00:00",
                "summary": "AI 手機拉貨",
            },
        ]
    }
    api_resp = _make_httpx_response(200, reports_data)
    mock_client = _mock_async_client(api_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await list_latest_reports(limit=50)

    assert "reports" in result
    assert len(result["reports"]) == 2
    r0 = result["reports"][0]
    assert r0["id"] == 102
    assert r0["stock_code"] == "2330"
    assert r0["stock_name"] == "台積電"
    assert r0["title"] == "資本支出"
    assert r0["date"] == "2024-10-15"
    assert r0["summary"] == "毛利率創高"


@pytest.mark.asyncio
async def test_list_latest_reports_nested_data():
    """Handles the {data:{data:[...]}} wrapper some UAnalyze endpoints return."""
    _auth.access_token = "tok"

    reports_data = {
        "data": {"data": [{"id": 5, "name": "1101", "stock_name": "某股", "question_type": "產業地位"}]}
    }
    api_resp = _make_httpx_response(200, reports_data)
    mock_client = _mock_async_client(api_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await list_latest_reports()

    assert "reports" in result
    r0 = result["reports"][0]
    assert r0["id"] == 5
    assert r0["stock_code"] == "1101"
    assert r0["stock_name"] == "某股"
    assert r0["title"] == "產業地位"


@pytest.mark.asyncio
async def test_list_latest_reports_failure():
    """API failure → error dict."""
    _auth.access_token = "tok"

    api_resp = _make_httpx_response(500, {"error": "internal"})
    mock_client = _mock_async_client(api_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await list_latest_reports()

    assert "error" in result


# --- fetch_eps_consensus() tests (Ticket 04, A3) ---


def _eps_module_payload():
    """Mimic the real EPSTracking response: data.data keyed by uaXXXXX_cp."""
    return {
        "data": {
            "data": {
                "ua60286_cp": {
                    "ChineseAccount": "實際EPS(A)",
                    "Data": {"2025Q1": 13.95, "2025Q2": 15.36, "2025Q3": 17.44, "2025Q4": 19.51, "2026Q1": 22.08},
                },
                "ua60285_cp": {
                    "ChineseAccount": "法人共識(F)",
                    "Data": {"2026Q2": 25.44, "2026Q3": 28.55, "2026Q4": 30.94, "2027Q1": 32.01, "2027Q2": 34.45},
                },
            }
        }
    }


def _rev_module_payload():
    """Mimic the real MonthlyRevenueTrackingConcensusl response."""
    return {
        "data": {
            "data": {
                "ua70274_cp": {
                    "ChineseAccount": "法人共識估計值",
                    "Data": {"09": 3850857083, "10": 4404409353, "11": 4926115010, "12": 5421984179},
                },
                "ua70248_cp": {
                    "ChineseAccount": "累計今年月營收",
                    "Data": {"05": 1961803721, "06": 2404483690, "07": 2872064238},
                },
            }
        }
    }


@pytest.mark.asyncio
async def test_fetch_eps_consensus_success():
    """Both domains return data → summary with eps + revenue (latest few only)."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    eps_resp = _make_httpx_response(200, _eps_module_payload())
    rev_resp = _make_httpx_response(200, _rev_module_payload())

    # fetch_eps_consensus opens two AsyncClient contexts (cronjob, then gidp).
    eps_client = _mock_async_client(eps_resp)
    rev_client = _mock_async_client(rev_resp)
    clients = iter([eps_client, rev_client])

    with patch("httpx.AsyncClient", side_effect=lambda **kwargs: next(clients)):
        result = await fetch_eps_consensus("2330", recent=4)

    assert result["symbol"] == "2330"
    # Only the latest 4 quarters kept.
    assert len(result["eps"]["實際EPS"]) == 4
    assert result["eps"]["實際EPS"][-1] == {"period": "2026Q1", "value": 22.08}
    assert result["eps"]["法人共識預估EPS"][-1] == {"period": "2027Q2", "value": 34.45}
    assert result["revenue"]["法人共識估計月營收"][-1]["month"] == "12"
    assert len(result["revenue"]["累計今年月營收"]) == 3


@pytest.mark.asyncio
async def test_fetch_eps_consensus_partial_gidp_fails():
    """cronjob ok, gidp fails → still return the eps section (best-effort)."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    eps_resp = _make_httpx_response(200, _eps_module_payload())
    rev_resp = _make_httpx_response(500, {"error": "boom"})
    eps_client = _mock_async_client(eps_resp)
    rev_client = _mock_async_client(rev_resp)
    clients = iter([eps_client, rev_client])

    with patch("httpx.AsyncClient", side_effect=lambda **kwargs: next(clients)):
        result = await fetch_eps_consensus("2330")

    assert "eps" in result
    assert "revenue" not in result


@pytest.mark.asyncio
async def test_fetch_eps_consensus_both_empty():
    """Both domains empty → error dict."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    empty_resp = _make_httpx_response(200, {"data": {"data": {}}})
    c1 = _mock_async_client(empty_resp)
    c2 = _mock_async_client(empty_resp)
    clients = iter([c1, c2])

    with patch("httpx.AsyncClient", side_effect=lambda **kwargs: next(clients)):
        result = await fetch_eps_consensus("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_eps_consensus_no_token():
    """Login fails → error dict, no requests made."""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_eps_consensus("2330")
    assert "error" in result


# --- fetch_per_share_metrics() tests (Ticket 04, A4) ---


def _pershare_payload():
    """Mimic the real PerShareValueForValuationModel response: data.data is a list."""
    return {
        "data": {
            "data": [
                {
                    "row_title_left": "每股自由現金流(元)",
                    "D2025": 43.61, "D2024": 37.08, "D2023": 12.95, "D2022": 16.18,
                    "D2021": 10.64, "D2020": 12.22, "D2019": 6.03,
                },
                {
                    "row_title_left": "每股EPS(元)",
                    "D2025": 66.26, "D2024": 45.25, "D2023": 32.34, "D2022": 39.2,
                    "D2021": 23.01, "D2020": 19.97,
                },
                {
                    "row_title_left": "年度ROE",
                    "D2025": 35.39, "D2024": 30.29, "D2023": 26.18,
                },
            ]
        }
    }


@pytest.mark.asyncio
async def test_fetch_per_share_metrics_success():
    """List parsed; only the latest N years kept per metric."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _pershare_payload())
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_per_share_metrics("2330", years=4)

    assert result["symbol"] == "2330"
    metrics = {m["name"]: m["values"] for m in result["metrics"]}
    # Free cash flow row has 7 years but only latest 4 kept.
    assert list(metrics["每股自由現金流(元)"].keys()) == ["2025", "2024", "2023", "2022"]
    assert metrics["每股自由現金流(元)"]["2025"] == 43.61
    # ROE row only has 3 years → all 3 kept.
    assert list(metrics["年度ROE"].keys()) == ["2025", "2024", "2023"]


@pytest.mark.asyncio
async def test_fetch_per_share_metrics_empty():
    """Empty list → error dict."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, {"data": {"data": []}})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_per_share_metrics("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_per_share_metrics_http_error():
    """Non-200 → error dict."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(500, {"error": "boom"})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_per_share_metrics("2330")

    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_per_share_metrics_no_token():
    """Login fails → error dict."""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_per_share_metrics("2330")
    assert "error" in result


# --- fetch_supply_chain() tests (Ticket 05, A7) ---


def _supply_payload(peers):
    """Mimic the real StockComparisonStockPool response: data.data is a list of code strings."""
    return {
        "data": {
            "data": list(peers),
            "type": "peer",
            "stock_code": "2330",
            "stock_name": "台積電",
            "country": "TW",
        }
    }


@pytest.mark.asyncio
async def test_fetch_supply_chain_success():
    """data.data is a list of plain code strings → peers list returned."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _supply_payload(["2303", "5347", "6770"]))
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_supply_chain("2330")

    assert result["symbol"] == "2330"
    assert result["peers"] == ["2303", "5347", "6770"]
    assert result["stock_name"] == "台積電"


@pytest.mark.asyncio
async def test_fetch_supply_chain_dict_elements():
    """Defensive: if elements are dicts, pull the code field."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    payload = {"data": {"data": [{"stock_code": "2303"}, {"code": "5347"}]}}
    resp = _make_httpx_response(200, payload)
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_supply_chain("2330")

    assert result["peers"] == ["2303", "5347"]


@pytest.mark.asyncio
async def test_fetch_supply_chain_empty():
    """Empty list → error dict."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, {"data": {"data": []}})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_supply_chain("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_supply_chain_http_error():
    """Non-200 → error dict."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(500, {"error": "boom"})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_supply_chain("2330")

    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_supply_chain_no_token():
    """Login fails → error dict."""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_supply_chain("2330")
    assert "error" in result


# --- fetch_order_visibility() tests (Ticket 05, A8) ---


@pytest.mark.asyncio
async def test_fetch_order_visibility_success():
    """Symbol found in ranking table → fields decoded and split into two sections."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    payload = {
        "data": {
            "type": "rankings_table",
            "column_title": [
                {"stock_title": "名稱"},
                {"ua60261_cp": "季報公佈日"},
                {"ua70030_cp": "月營收年增率"},
                {"ua60255_cp": "合約負債佔營收幾%"},
                {"ua60213_cp": "季合約負債季增率"},
            ],
            "data": [
                {
                    "stock_title": "1111 別檔",
                    "stock_code": "1111",
                    "stock_name": "別檔",
                    "ua60261_cp": "2026/01/01",
                    "ua70030_cp": 1.0,
                    "ua60255_cp": 0.0,
                    "ua60213_cp": 0.0,
                },
                {
                    "stock_title": "3661 世芯-KY",
                    "stock_code": "3661",
                    "stock_name": "世芯-KY",
                    "ua60261_cp": "2026/07/29",
                    "ua70030_cp": 34.9,
                    "ua60255_cp": 7.3,
                    "ua60213_cp": 17.3,
                },
            ],
        }
    }
    resp = _make_httpx_response(200, payload)

    with patch("httpx.AsyncClient", side_effect=lambda **kwargs: _mock_async_client(resp)):
        result = await fetch_order_visibility("3661")

    assert result["symbol"] == "3661"
    assert result["stock_name"] == "世芯-KY"
    # Non-contract-liability labels go to order_visibility (decoded via column_title).
    assert result["order_visibility"]["季報公佈日"] == "2026/07/29"
    assert result["order_visibility"]["月營收年增率"] == 34.9
    # Contract-liability labels split into their own section.
    assert result["contract_liability"] == {
        "合約負債佔營收幾%": 7.3,
        "季合約負債季增率": 17.3,
    }
    # stock_code/stock_name/stock_title never leak into the metric tables.
    assert "stock_code" not in result["order_visibility"]
    assert "stock_name" not in result["order_visibility"]


@pytest.mark.asyncio
async def test_fetch_order_visibility_unknown_code_falls_back_to_code():
    """A column with no title mapping keeps its raw code as the label (order section)."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    payload = {
        "data": {
            "column_title": [{"ua60255_cp": "合約負債佔營收幾%"}],
            "data": [
                {
                    "stock_code": "2330",
                    "stock_name": "台積電",
                    "ua99999_cp": "神秘欄位",
                    "ua60255_cp": 1.2,
                }
            ],
        }
    }
    resp = _make_httpx_response(200, payload)

    with patch("httpx.AsyncClient", side_effect=lambda **kwargs: _mock_async_client(resp)):
        result = await fetch_order_visibility("2330")

    assert result["order_visibility"]["ua99999_cp"] == "神秘欄位"
    assert result["contract_liability"]["合約負債佔營收幾%"] == 1.2


@pytest.mark.asyncio
async def test_fetch_order_visibility_symbol_not_in_table():
    """Ranking table returned but symbol absent → error dict."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    payload = {
        "data": {
            "column_title": [{"ua60261_cp": "季報公佈日"}],
            "data": [{"stock_code": "1111", "stock_name": "別檔", "ua60261_cp": "x"}],
        }
    }
    resp = _make_httpx_response(200, payload)

    with patch("httpx.AsyncClient", side_effect=lambda **kwargs: _mock_async_client(resp)):
        result = await fetch_order_visibility("2330")

    assert "error" in result
    assert "2330" in result["error"]
    assert "訂單能見度" in result["error"]


@pytest.mark.asyncio
async def test_fetch_order_visibility_empty_table():
    """Ranking table empty/missing → error dict."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, {"data": {"data": [], "country": "TW"}})

    with patch("httpx.AsyncClient", side_effect=lambda **kwargs: _mock_async_client(resp)):
        result = await fetch_order_visibility("2330")

    assert "error" in result
    assert "2330" in result["error"]
    assert "訂單能見度" in result["error"]


@pytest.mark.asyncio
async def test_fetch_order_visibility_no_token():
    """Login fails → error dict."""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_order_visibility("2330")
    assert "error" in result


# --- CLI test ---


def test_cli_output():
    """CLI invocation with no credentials prints error JSON and exits 1."""
    env = {
        "PATH": "/usr/bin:/bin",
        "UANALYZE_EMAIL": "",
        "UANALYZE_PASSWORD": "",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "tools.uanalyze", "2330"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(__file__).rsplit("/tests/", 1)[0],
    )
    assert proc.returncode == 1
    output = json.loads(proc.stdout)
    assert "error" in output


def test_cli_no_args():
    """CLI with no args prints usage error."""
    env = {
        "PATH": "/usr/bin:/bin",
        "UANALYZE_EMAIL": "",
        "UANALYZE_PASSWORD": "",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "tools.uanalyze"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(__file__).rsplit("/tests/", 1)[0],
    )
    assert proc.returncode == 1
    output = json.loads(proc.stdout)
    assert "error" in output
    assert "用法" in output["error"]


# --- DCF valuation tests (Ticket 06, A5) ---


def _dcf_eps_payload():
    """Mimic real EPSRevenueConsensusEstimate: ua50187_cp.Data year->EPS, (f)=forecast.

    Matches the shape verified against the live gidp endpoint for 2330.
    """
    return {
        "data": {
            "data": {
                "ua50187_cp": {
                    "ChineseAccount": "EPS",
                    "Data": {
                        "2023": 32.34,
                        "2024": 45.25,
                        "2025": 66.26,
                        "2026(f)": 109.58,
                        "2027(f)": 151.15,
                        "2028(f)": 190.09,
                        "2029(f)": 239.09,
                        "2030(f)": 293.74,
                    },
                }
            }
        }
    }


def _dcf_rev_payload():
    """Mimic real MonthlyRevenueTrackingConcensuslModule: ua70306_cp.Data month->pct."""
    return {
        "data": {
            "data": {
                "ua70306_cp": {
                    "ChineseAccount": "累計營收超法人預期(%)",
                    "Data": {"01": -1.9, "02": -5.1, "03": 0, "04": -1.3, "05": -1.9, "06": 0.1, "07": 0.1},
                }
            }
        }
    }


def _dcf_client_router(eps_payload, rev_payload):
    """Return an httpx.AsyncClient side_effect that routes by request URL.

    fetch_dcf_valuation opens two AsyncClient contexts concurrently (asyncio.gather);
    route on the URL passed to get() rather than relying on creation order.
    """
    eps_resp = _make_httpx_response(200, eps_payload) if eps_payload is not None else _make_httpx_response(500, {})
    rev_resp = _make_httpx_response(200, rev_payload) if rev_payload is not None else _make_httpx_response(500, {})

    def _make_get():
        async def _get(url, *args, **kwargs):
            if "EPSRevenueConsensusEstimate" in url:
                return eps_resp
            return rev_resp

        return _get

    def _factory(**kwargs):
        client = AsyncMock()
        client.get = _make_get()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    return _factory


# --- _compute_dcf pure-function tests (the most testable part) ---


def test_compute_dcf_regression_base_year_2024():
    """Regression lock: fixed base_year + fixed 2330-shaped inputs → exact outputs.

    Values computed once from the ported formula and frozen here so any accidental
    change to the DCF math is caught. base_year injected to avoid time dependence.
    """
    eps_hist = {2023: 32.34, 2024: 45.25, 2025: 66.26}
    eps_fore = {2026: 109.58, 2027: 151.15, 2028: 190.09, 2029: 239.09, 2030: 293.74}

    (
        base_ttm,
        v_2025,
        v_2026E,
        v_2027E,
        far_fore_yr,
        far_fore_eps,
        confidence_level,
        intrinsic_val,
    ) = _compute_dcf(eps_hist, eps_fore, "+0.1%", 0.1, current_month=8, base_year=2025)

    assert v_2025 == 66.26
    assert v_2026E == 109.58
    assert v_2027E == 151.15
    assert far_fore_yr == 2030
    assert far_fore_eps == 293.74
    assert confidence_level == "高 (法人完全直連 N=5)"
    # Frozen regression values (see report; recomputed from the ported formula).
    assert round(base_ttm, 2) == 91.57
    assert intrinsic_val == 3101.0


def test_compute_dcf_high_growth_discount_confidence():
    """High-growth, short horizon (N=2, marginal YoY>50%) → confidence discount path."""
    eps_hist = {2024: 5.0, 2025: 8.0}
    eps_fore = {2026: 20.0, 2027: 40.0}

    (
        base_ttm,
        v_2025,
        v_2026E,
        v_2027E,
        far_fore_yr,
        far_fore_eps,
        confidence_level,
        intrinsic_val,
    ) = _compute_dcf(eps_hist, eps_fore, "+5.0%", 5.0, current_month=8, base_year=2025)

    # N = far_fore_yr(2027) - base_year(2025) = 2 → triggers the N<=2 discount branch.
    assert far_fore_yr == 2027
    assert confidence_level == "⚠️ 低 (N≤2極端外推打折)"
    # Frozen regression value under the discounted-growth path.
    assert intrinsic_val == 512.55


def test_compute_dcf_no_revenue_multiplier():
    """rev_gap_pct_str == '-' → rev_multiplier neutral (1.0); base_ttm is pure weighting."""
    eps_hist = {2024: 10.0, 2025: 10.0}
    eps_fore = {2026: 10.0, 2027: 10.0, 2028: 10.0}

    base_ttm, *_ = _compute_dcf(eps_hist, eps_fore, "-", 0.0, current_month=8, base_year=2025)
    # w_hist*v_2025 + w_fore*v_2026 = (5/12)*10 + (7/12)*10 = 10.0 exactly.
    assert round(base_ttm, 6) == 10.0


# --- fetch_dcf_valuation tests (mock httpx) ---


@pytest.mark.asyncio
async def test_fetch_dcf_valuation_success():
    """Both gidp endpoints return data → key-number summary dict."""
    _auth.access_token = "tok"

    factory = _dcf_client_router(_dcf_eps_payload(), _dcf_rev_payload())
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_dcf_valuation("2330")

    assert result["symbol"] == "2330"
    assert "每股合理內在價值" in result
    assert "1年後前瞻合理價值" in result
    assert "當前時間加權基期" in result
    assert result["營收動能"] == "+0.1%"
    assert result["2025實際獲利"] == 66.26
    assert result["2026E"] == 109.58
    assert result["最遠預估年份及獲利"] == "2030E:293.74元"
    assert "信心度" in result
    # forward = intrinsic*(1+WACC) - v_2026E; sanity: numeric and consistent.
    expected_fwd = round(result["每股合理內在價值"] * (1.0 + WACC) - result["2026E"], 2)
    assert result["1年後前瞻合理價值"] == expected_fwd


@pytest.mark.asyncio
async def test_fetch_dcf_valuation_eps_insufficient():
    """EPS endpoint empty → clear '資料不足' error, no crash."""
    _auth.access_token = "tok"

    empty_eps = {"data": {"data": {"ua50187_cp": {"Data": {}}}}}
    factory = _dcf_client_router(empty_eps, _dcf_rev_payload())
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_dcf_valuation("2330")

    assert "error" in result
    assert "EPS 資料不足" in result["error"]


@pytest.mark.asyncio
async def test_fetch_dcf_valuation_no_token():
    """Login fails → error dict."""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_dcf_valuation("2330")
    assert "error" in result


# --- fetch_transcript_list() / fetch_transcript_detail() tests (Ticket 07) ---


def _transcript_list_payload(items):
    """Mimic gidp WebStockInfo: data.data.ua80305_cp is the 逐字稿 row with a Data list."""
    return {
        "data": {
            "data": {
                "ua12345_cp": {"ChineseAccount": "收盤價", "Data": 2410.0},
                "ua80305_cp": {"ChineseAccount": "逐字稿", "Data": list(items)},
            }
        }
    }


@pytest.mark.asyncio
async def test_fetch_transcript_list_success():
    """逐字稿 row present → transcripts list (newest-first, {date,id})."""
    items = [
        {"Data": "2026/07/16", "id": "202607162330"},
        {"Data": "2026/04/16", "id": "202604162330"},
    ]
    resp = _make_httpx_response(200, _transcript_list_payload(items))
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_transcript_list("2330")

    assert result["symbol"] == "2330"
    assert result["transcripts"] == [
        {"date": "2026/07/16", "id": "202607162330"},
        {"date": "2026/04/16", "id": "202604162330"},
    ]


@pytest.mark.asyncio
async def test_fetch_transcript_list_no_data():
    """No 逐字稿 row → error dict."""
    payload = {"data": {"data": {"ua12345_cp": {"ChineseAccount": "收盤價", "Data": 1}}}}
    resp = _make_httpx_response(200, payload)
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_transcript_list("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_transcript_list_http_error():
    """Non-200 → error dict."""
    resp = _make_httpx_response(500, {})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_transcript_list("2330")

    assert "error" in result


def _transcript_detail_payload(transcript_text):
    """Mimic cronjob TranscriptDetail: full text nested at data.data.data."""
    return {
        "status": "ok",
        "state": 1,
        "data": {
            "data": {
                "id": "202607162330",
                "stock": "2330",
                "date": "20260716",
                "title": "台積電法說逐字稿",
                "transcript": transcript_text,
            },
            "type": "transcript",
        },
    }


@pytest.mark.asyncio
async def test_fetch_transcript_detail_success():
    """Full text present → detail dict with transcript/title/date/stock."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _transcript_detail_payload("全文內容" * 100))
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_transcript_detail("202607162330")

    assert result["id"] == "202607162330"
    assert result["title"] == "台積電法說逐字稿"
    assert result["date"] == "20260716"
    assert result["stock"] == "2330"
    assert result["transcript"] == "全文內容" * 100


@pytest.mark.asyncio
async def test_fetch_transcript_detail_empty_transcript():
    """Empty transcript → error dict."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _transcript_detail_payload(""))
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_transcript_detail("202607162330")

    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_transcript_detail_http_error():
    """Non-200 → error dict."""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(403, {})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_transcript_detail("202607162330")

    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_transcript_detail_uses_country_twn():
    """全文請求必須帶 country=TWN（非 TW）。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _transcript_detail_payload("內容"))
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await fetch_transcript_detail("202607162330")

    call = mock_client.get.call_args
    assert call.kwargs["params"]["country"] == "TWN"
    assert call.kwargs["params"]["id"] == "202607162330"


# --- analyze_multi（批次並行多面向）---

_ENV = {"UANALYZE_EMAIL": "a@b.com", "UANALYZE_PASSWORD": "pass"}


@pytest.mark.asyncio
async def test_analyze_multi_runs_all_prompts():
    """並行跑多個面向，全部成功時 results 含每個面向、ok 列出全部。"""
    async def fake_completion(symbol, prompt):
        return {"analysis": f"{prompt} 的分析", "prompt": prompt, "symbol": symbol}

    with patch.dict("os.environ", _ENV), patch(
        "tools.uanalyze.get_completion", side_effect=fake_completion
    ), patch("tools.uanalyze._auth.ensure_token", new=AsyncMock(return_value="tok")):
        res = await analyze_multi("4906", ["近況發展", "利多因素", "利空因素"])

    assert res["symbol"] == "4906"
    assert res["ok"] == ["近況發展", "利多因素", "利空因素"]
    assert res["failed"] == []
    assert res["results"]["近況發展"]["analysis"] == "近況發展 的分析"


@pytest.mark.asyncio
async def test_analyze_multi_isolates_single_failure():
    """單一面向失敗（無資料 / 例外）只記在該面向，不拖垮其他。"""
    async def fake_completion(symbol, prompt):
        if prompt == "產品線分析":
            return {"error": "無資料"}
        if prompt == "利空因素":
            raise RuntimeError("timeout")
        return {"analysis": "ok", "prompt": prompt, "symbol": symbol}

    with patch.dict("os.environ", _ENV), patch(
        "tools.uanalyze.get_completion", side_effect=fake_completion
    ), patch("tools.uanalyze._auth.ensure_token", new=AsyncMock(return_value="tok")):
        res = await analyze_multi("4906", ["近況發展", "產品線分析", "利空因素"])

    assert res["ok"] == ["近況發展"]
    assert set(res["failed"]) == {"產品線分析", "利空因素"}
    assert "error" in res["results"]["產品線分析"]
    assert "error" in res["results"]["利空因素"]  # 例外被捕捉成 error


@pytest.mark.asyncio
async def test_analyze_multi_respects_concurrency_limit():
    """Semaphore 限制同時在跑的面向數不超過 concurrency。"""
    active = 0
    max_active = 0

    async def fake_completion(symbol, prompt):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return {"analysis": "x", "prompt": prompt, "symbol": symbol}

    with patch.dict("os.environ", _ENV), patch(
        "tools.uanalyze.get_completion", side_effect=fake_completion
    ), patch("tools.uanalyze._auth.ensure_token", new=AsyncMock(return_value="tok")):
        res = await analyze_multi(
            "4906", [f"面向{i}" for i in range(10)], concurrency=3
        )

    assert len(res["ok"]) == 10
    assert max_active <= 3  # 從未同時超過 3 個


@pytest.mark.asyncio
async def test_analyze_multi_dedupes_prompts():
    """重複面向去重但保留順序。"""
    async def fake_completion(symbol, prompt):
        return {"analysis": "x", "prompt": prompt, "symbol": symbol}

    with patch.dict("os.environ", _ENV), patch(
        "tools.uanalyze.get_completion", side_effect=fake_completion
    ), patch("tools.uanalyze._auth.ensure_token", new=AsyncMock(return_value="tok")):
        res = await analyze_multi("4906", ["近況發展", "利多因素", "近況發展"])

    assert res["requested"] == ["近況發展", "利多因素"]


@pytest.mark.asyncio
async def test_analyze_multi_empty_prompts_errors():
    """沒給面向回錯誤。"""
    with patch.dict("os.environ", _ENV):
        res = await analyze_multi("4906", [])
    assert "error" in res


@pytest.mark.asyncio
async def test_analyze_multi_missing_credentials_errors():
    """缺帳密回錯誤、不呼叫 API。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        res = await analyze_multi("4906", ["近況發展"])
    assert "error" in res


# --- fetch_valuation_bands() tests (A10 相對估值 PE/PB Band) ---


def _hist_per_payload():
    """Mimic cronjob HistoricalPer: data.data 本益比月序列 + data.refline 帶。"""
    return {
        "data": {
            "stock_name": "台積電",
            "data": {
                "ua70002_cp": {
                    "ChineseAccount": "本益比",
                    "Data": {"202506": 20.0, "202507": 22.0, "202508": 24.0, "202509": 30.0},
                }
            },
            "refline": {
                "ua70003_cp": {"ChineseAccount": "本益比-10年平均", "Data": 17.8},
                "ua70005_cp": {"ChineseAccount": "本益比(+1標準差)", "Data": 29.8},
                "ua70006_cp": {"ChineseAccount": "本益比(+2標準差)", "Data": 39.9},
                "ua70007_cp": {"ChineseAccount": "本益比(-1標準差)", "Data": 9.5},
            },
        }
    }


def _hist_pbr_payload():
    """Mimic cronjob HistoricalPbr: data.data 股價淨值比月序列 + refline。"""
    return {
        "data": {
            "data": {
                "ua70009_cp": {
                    "ChineseAccount": "股價淨值比",
                    "Data": {"202507": 1.0, "202508": 1.1, "202509": 1.2},
                }
            },
            "refline": {
                "ua70010_cp": {"ChineseAccount": "股價淨值比-10年平均", "Data": 1.2},
                "ua70012_cp": {"ChineseAccount": "股價淨值比(+1標準差)", "Data": 1.3},
            },
        }
    }


def _pe_band_payload():
    """Mimic cronjob PE_Band: 同產業本益比中位數 藏在 data.refdata。"""
    return {
        "data": {
            "data": {"ua70039_cp": {"ChineseAccount": "EPS(換算成月)", "Data": {"202509": 5.0}}},
            "refdata": {
                "ua70055_cp": {"ChineseAccount": "本益比(月)-近120個月中位數-最高值", "Data": 52.3},
                "ua70056_cp": {"ChineseAccount": "同產業本益比中位數", "Data": 15.2},
            },
        }
    }


def _valuation_client_router(per_payload, pbr_payload, band_payload):
    """Route the 3 concurrent AsyncClient.get() calls by endpoint in URL."""
    def _resp(p):
        return _make_httpx_response(200, p) if p is not None else _make_httpx_response(500, {})

    per_r, pbr_r, band_r = _resp(per_payload), _resp(pbr_payload), _resp(band_payload)

    def _make_get():
        async def _get(url, *args, **kwargs):
            if "HistoricalPer" in url:
                return per_r
            if "HistoricalPbr" in url:
                return pbr_r
            return band_r  # PE_Band
        return _get

    def _factory(**kwargs):
        client = AsyncMock()
        client.get = _make_get()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    return _factory


@pytest.mark.asyncio
async def test_fetch_valuation_bands_success():
    """三端點齊全 → pe/pb 摘要含最新值、10年均、標準差帶、百分位、同業中位數。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _valuation_client_router(_hist_per_payload(), _hist_pbr_payload(), _pe_band_payload())
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_valuation_bands("2330")

    assert result["symbol"] == "2330"
    assert result["stock_name"] == "台積電"
    pe = result["pe"]
    assert pe["latest_month"] == "202509"
    assert pe["latest"] == 30.0
    assert pe["avg_10y"] == 17.8
    # 現值 30.0 大於序列中 3/4 筆(20/22/24) → 75.0 百分位
    assert pe["percentile_in_history"] == 75.0
    assert pe["std_bands"]["本益比(+1標準差)"] == 29.8
    assert pe["std_bands"]["本益比(-1標準差)"] == 9.5
    assert pe["peer_median"] == 15.2  # 來自 PE_Band.refdata

    pb = result["pb"]
    assert pb["latest_month"] == "202509"
    assert pb["latest"] == 1.2
    assert pb["avg_10y"] == 1.2
    assert pb["percentile_in_history"] == 66.7  # 1.2 高於 1.0/1.1 兩筆(共3筆含自身)


@pytest.mark.asyncio
async def test_fetch_valuation_bands_pe_only():
    """PB 端點掛掉、PE 正常 → 仍回 pe 段（best-effort，不整體失敗）。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _valuation_client_router(_hist_per_payload(), None, _pe_band_payload())
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_valuation_bands("2330")

    assert "pe" in result
    assert "pb" not in result


@pytest.mark.asyncio
async def test_fetch_valuation_bands_peer_median_optional():
    """PE_Band 掛掉 → pe 段仍在，只是沒有 peer_median。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _valuation_client_router(_hist_per_payload(), _hist_pbr_payload(), None)
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_valuation_bands("2330")

    assert "pe" in result
    assert "peer_median" not in result["pe"]


@pytest.mark.asyncio
async def test_fetch_valuation_bands_all_empty():
    """三端點全掛 → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _valuation_client_router(None, None, None)
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_valuation_bands("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_valuation_bands_no_token():
    """登入失敗 → error dict。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_valuation_bands("2330")
    assert "error" in result


# --- fetch_institutional_chips() tests (A11 三大法人籌碼) ---


def _chips_payload():
    """Mimic cronjob InstitutionalInvestorsNet: list（最新在前），raw 欄位為買賣超。"""
    return {
        "data": {
            "stock_name": "台積電",
            "column_title": [
                {"row_title_center": "年度/月份"},
                {"raw80050": "外資(張)"},
                {"raw80053": "投信(張)"},
                {"raw80062": "自營商(張)"},
                {"raw80063": "三大法人合計(張)"},
            ],
            "data": [
                {"row_title_center": 20260911, "raw80050": 1000.0, "raw80053": 200.0, "raw80062": 50.0, "raw80063": 1250.0},
                {"row_title_center": 20260910, "raw80050": -500.0, "raw80053": 100.0, "raw80062": -30.0, "raw80063": -430.0},
                {"row_title_center": 20260909, "raw80050": 300.0, "raw80053": 0.0, "raw80062": 20.0, "raw80063": 320.0},
            ],
        }
    }


@pytest.mark.asyncio
async def test_fetch_institutional_chips_success():
    """list 解析、最新在前、近 N 日合計正確。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _chips_payload())
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_institutional_chips("2330", recent=20)

    assert result["symbol"] == "2330"
    assert result["stock_name"] == "台積電"
    assert result["unit"] == "張"
    # 最新在前
    assert result["recent_days"][0]["date"] == 20260911
    assert result["recent_days"][0]["外資"] == 1000.0
    # 近 3 日合計
    s = result["sum_recent"]
    assert s["天數"] == 3
    assert s["外資"] == 800.0  # 1000 - 500 + 300
    assert s["投信"] == 300.0  # 200 + 100 + 0
    assert s["自營商"] == 40.0  # 50 - 30 + 20
    assert s["合計"] == 1140.0  # 1250 - 430 + 320


@pytest.mark.asyncio
async def test_fetch_institutional_chips_respects_recent_limit():
    """recent 限制只取最近 N 筆。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _chips_payload())
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_institutional_chips("2330", recent=2)

    assert len(result["recent_days"]) == 2
    assert result["sum_recent"]["天數"] == 2
    assert result["sum_recent"]["外資"] == 500.0  # 1000 - 500（只前2筆）


@pytest.mark.asyncio
async def test_fetch_institutional_chips_empty():
    """空 list → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, {"data": {"data": []}})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_institutional_chips("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_institutional_chips_http_error():
    """Non-200 → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(500, {})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_institutional_chips("2330")

    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_institutional_chips_no_token():
    """登入失敗 → error dict。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_institutional_chips("2330")
    assert "error" in result


# --- fetch_profit_margins() tests (A12 三率趨勢) ---


def _margins_payload():
    """Mimic cronjob MajorProfitMargins: dict of 率序列（季度 key）。"""
    return {
        "data": {
            "stock_name": "台積電",
            "data": {
                "ua60089_cp": {
                    "ChineseAccount": "毛利率",
                    "Data": {"2025Q3": 59.0, "2025Q4": 59.5, "2026Q1": 58.8, "2026Q2": 58.6},
                },
                "ua60026_cp": {
                    "ChineseAccount": "營業利益率",
                    "Data": {"2025Q3": 49.0, "2025Q4": 49.5, "2026Q1": 48.5, "2026Q2": 49.6},
                },
                "ua60109_cp": {
                    "ChineseAccount": "稅後淨利率",
                    "Data": {"2025Q3": 42.0, "2025Q4": 43.1, "2026Q1": 42.9, "2026Q2": 42.7},
                },
                "ua99999_cp": {  # 非目標列，應被忽略
                    "ChineseAccount": "其他不相關指標",
                    "Data": {"2026Q2": 1.0},
                },
            },
        }
    }


@pytest.mark.asyncio
async def test_fetch_profit_margins_success():
    """三率解析、最新一季快照正確、忽略非目標列。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _margins_payload())
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_profit_margins("2330", recent=8)

    assert result["symbol"] == "2330"
    assert result["stock_name"] == "台積電"
    assert result["unit"] == "%"
    assert set(result["margins"].keys()) == {"毛利率", "營業利益率", "稅後淨利率"}
    # 序列最舊→最新
    gm = result["margins"]["毛利率"]
    assert gm[0]["period"] == "2025Q3"
    assert gm[-1]["period"] == "2026Q2"
    assert gm[-1]["value"] == 58.6
    # 最新一季快照
    assert result["latest"]["period"] == "2026Q2"
    assert result["latest"]["毛利率"] == 58.6
    assert result["latest"]["稅後淨利率"] == 42.7
    # 非目標列被忽略
    assert "其他不相關指標" not in result["margins"]


@pytest.mark.asyncio
async def test_fetch_profit_margins_recent_limit():
    """recent 限制只取最近 N 季。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _margins_payload())
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_profit_margins("2330", recent=2)

    gm = result["margins"]["毛利率"]
    assert len(gm) == 2
    assert gm[0]["period"] == "2026Q1"
    assert gm[-1]["period"] == "2026Q2"


@pytest.mark.asyncio
async def test_fetch_profit_margins_empty():
    """空 dict → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, {"data": {"data": {}}})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_profit_margins("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_profit_margins_http_error():
    """Non-200 → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(500, {})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_profit_margins("2330")

    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_profit_margins_no_token():
    """登入失敗 → error dict。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_profit_margins("2330")
    assert "error" in result


# --- fetch_cash_flow_trend() tests (A13 現金流趨勢) ---


def _cashflow_payload():
    """Mimic cronjob CashFlowTrend: dict of 現金流序列，資料在 PeriodData。"""
    return {
        "data": {
            "stock_name": "台積電",
            "data": {
                "AAAA": {"ChineseAccount": "營業活動現金流",
                         "PeriodData": {"2025Q3": 100.0, "2025Q4": 120.0, "2026Q1": 110.0, "2026Q2": 130.0}},
                "BBBB": {"ChineseAccount": "投資活動現金流",
                         "PeriodData": {"2025Q3": -80.0, "2025Q4": -90.0, "2026Q1": -70.0, "2026Q2": -85.0}},
                "CCCC": {"ChineseAccount": "籌資活動現金流",
                         "PeriodData": {"2025Q3": -10.0, "2025Q4": -20.0, "2026Q1": -15.0, "2026Q2": -25.0}},
                "ua90009_xbrl": {"ChineseAccount": "自由現金流",
                                 "PeriodData": {"2025Q3": 20.0, "2025Q4": 30.0, "2026Q1": 40.0, "2026Q2": 45.0}},
            },
        }
    }


@pytest.mark.asyncio
async def test_fetch_cash_flow_trend_success():
    """四條現金流解析、PeriodData 讀取、最新快照正確。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _cashflow_payload())
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_cash_flow_trend("2330", recent=8)

    assert result["symbol"] == "2330"
    assert result["stock_name"] == "台積電"
    assert result["unit"] == "千元"
    assert set(result["flows"].keys()) == {"營業活動現金流", "投資活動現金流", "籌資活動現金流", "自由現金流"}
    fcf = result["flows"]["自由現金流"]
    assert fcf[0]["period"] == "2025Q3"
    assert fcf[-1]["period"] == "2026Q2"
    assert fcf[-1]["value"] == 45.0
    assert result["latest"]["period"] == "2026Q2"
    assert result["latest"]["自由現金流"] == 45.0


@pytest.mark.asyncio
async def test_fetch_cash_flow_trend_recent_limit():
    """recent 限制只取最近 N 季。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _cashflow_payload())
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_cash_flow_trend("2330", recent=2)

    fcf = result["flows"]["自由現金流"]
    assert len(fcf) == 2
    assert fcf[0]["period"] == "2026Q1"


@pytest.mark.asyncio
async def test_fetch_cash_flow_trend_empty():
    """空 dict → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, {"data": {"data": {}}})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_cash_flow_trend("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_cash_flow_trend_http_error():
    """Non-200 → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(500, {})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_cash_flow_trend("2330")

    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_cash_flow_trend_no_token():
    """登入失敗 → error dict。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_cash_flow_trend("2330")
    assert "error" in result


# --- fetch_dividend_policy() tests (A14 股利政策) ---


def _dividend_payload():
    """Mimic cronjob CashDividendPayoutRatio: 現金股息 + 發放率，年度序列（Data）。"""
    return {
        "data": {
            "stock_name": "台積電",
            "data": {
                "ua50001_cp": {"ChineseAccount": "現金股息合計",
                               "Data": {"2022": 11.0, "2023": 11.0, "2024": 13.5, "2025": 16.0}},
                "ua50009_cp": {"ChineseAccount": "現金股息發放率％",
                               "Data": {"2022": 27.9, "2023": 34.0, "2024": 29.8, "2025": 24.2}},
            },
        }
    }


@pytest.mark.asyncio
async def test_fetch_dividend_policy_success():
    """現金股息與發放率合併為年度列、最新一年快照正確。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _dividend_payload())
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_dividend_policy("2330", years=10)

    assert result["symbol"] == "2330"
    assert result["stock_name"] == "台積電"
    divs = result["dividends"]
    assert divs[0]["year"] == "2022"
    assert divs[-1]["year"] == "2025"
    assert divs[-1]["現金股息"] == 16.0
    assert divs[-1]["發放率(%)"] == 24.2
    assert result["latest"]["year"] == "2025"


@pytest.mark.asyncio
async def test_fetch_dividend_policy_years_limit():
    """years 限制只取最近 N 年。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, _dividend_payload())
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_dividend_policy("2330", years=2)

    divs = result["dividends"]
    assert len(divs) == 2
    assert divs[0]["year"] == "2024"
    assert divs[-1]["year"] == "2025"


@pytest.mark.asyncio
async def test_fetch_dividend_policy_empty():
    """空 dict → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    resp = _make_httpx_response(200, {"data": {"data": {}}})
    mock_client = _mock_async_client(resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_dividend_policy("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_dividend_policy_no_token():
    """登入失敗 → error dict。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_dividend_policy("2330")
    assert "error" in result


# --- fetch_peers_comparison() tests (A15 同業多維比較，組合既有函式) ---


@pytest.mark.asyncio
async def test_fetch_peers_comparison_success():
    """組合 supply + valuation + margins：本檔在首列，同業接續，指標填入。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    async def fake_supply(sym):
        return {"symbol": sym, "peers": ["2303", "2330", "6770"]}  # 含自身，應被去重

    async def fake_valuation(code):
        return {"symbol": code, "pe": {"latest": 20.0}, "pb": {"latest": 3.0}}

    async def fake_margins(code):
        return {"symbol": code, "latest": {"毛利率": 50.0, "營業利益率": 40.0, "稅後淨利率": 35.0}}

    with patch("tools.uanalyze.fetch_supply_chain", side_effect=fake_supply), patch(
        "tools.uanalyze.fetch_valuation_bands", side_effect=fake_valuation
    ), patch("tools.uanalyze.fetch_profit_margins", side_effect=fake_margins), patch(
        "tools.uanalyze._auth.ensure_token", new=AsyncMock(return_value="tok")
    ):
        result = await fetch_peers_comparison("2330", max_peers=5)

    assert result["symbol"] == "2330"
    # 本檔在首，自身從 peers 去重（2330 不重複出現）
    assert result["peers_compared"][0] == "2330"
    assert result["peers_compared"].count("2330") == 1
    assert "2303" in result["peers_compared"]
    first = result["rows"][0]
    assert first["stock"] == "2330"
    assert first["本益比"] == 20.0
    assert first["毛利率"] == 50.0


@pytest.mark.asyncio
async def test_fetch_peers_comparison_partial_failure_isolated():
    """某檔取數失敗只該列留空，不影響其他檔。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    async def fake_supply(sym):
        return {"symbol": sym, "peers": ["2303"]}

    async def fake_valuation(code):
        if code == "2303":
            return {"error": "無資料"}
        return {"symbol": code, "pe": {"latest": 20.0}, "pb": {"latest": 3.0}}

    async def fake_margins(code):
        if code == "2303":
            return {"error": "無資料"}
        return {"symbol": code, "latest": {"毛利率": 50.0}}

    with patch("tools.uanalyze.fetch_supply_chain", side_effect=fake_supply), patch(
        "tools.uanalyze.fetch_valuation_bands", side_effect=fake_valuation
    ), patch("tools.uanalyze.fetch_profit_margins", side_effect=fake_margins), patch(
        "tools.uanalyze._auth.ensure_token", new=AsyncMock(return_value="tok")
    ):
        result = await fetch_peers_comparison("2330")

    rows = {r["stock"]: r for r in result["rows"]}
    assert rows["2330"]["本益比"] == 20.0
    # 2303 取數失敗 → 只有 stock 欄
    assert list(rows["2303"].keys()) == ["stock"]


@pytest.mark.asyncio
async def test_fetch_peers_comparison_no_metric_errors():
    """本檔與同業全無可比指標 → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    async def fake_supply(sym):
        return {"symbol": sym, "peers": []}

    async def fake_fail(code):
        return {"error": "無資料"}

    with patch("tools.uanalyze.fetch_supply_chain", side_effect=fake_supply), patch(
        "tools.uanalyze.fetch_valuation_bands", side_effect=fake_fail
    ), patch("tools.uanalyze.fetch_profit_margins", side_effect=fake_fail), patch(
        "tools.uanalyze._auth.ensure_token", new=AsyncMock(return_value="tok")
    ):
        result = await fetch_peers_comparison("9999")

    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_peers_comparison_no_token():
    """登入失敗 → error dict。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_peers_comparison("2330")
    assert "error" in result


# --- fetch_margin_trading() tests (A16 信用交易) ---


def _margin_payload():
    """Mimic cronjob MarginBalanceVSMarginUtilization: 融資餘額 + 使用率（Data，日序列）。"""
    return {
        "data": {
            "stock_name": "台積電",
            "data": {
                "raw80091": {"ChineseAccount": "融資餘額",
                             "Data": {"20260909": 36000.0, "20260910": 36500.0, "20260911": 36728.0}},
                "raw80093": {"ChineseAccount": "融資使用率",
                             "Data": {"20260909": 1.9, "20260910": 1.92, "20260911": 1.95}},
            },
        }
    }


def _short_payload():
    """Mimic cronjob ShortInterestVSShortSellUtilization: 融券餘額 + 使用率。"""
    return {
        "data": {
            "data": {
                "raw80099": {"ChineseAccount": "融券餘額",
                             "Data": {"20260909": 40.0, "20260910": 45.0, "20260911": 50.0}},
                "raw80101": {"ChineseAccount": "融券使用率",
                             "Data": {"20260909": 0.0, "20260910": 0.0, "20260911": 0.0}},
            },
        }
    }


def _margin_client_router(margin_payload, short_payload):
    """Route the 2 concurrent gets by endpoint in URL."""
    def _resp(p):
        return _make_httpx_response(200, p) if p is not None else _make_httpx_response(500, {})

    m_r, s_r = _resp(margin_payload), _resp(short_payload)

    def _make_get():
        async def _get(url, *args, **kwargs):
            if "MarginBalanceVSMarginUtilization" in url:
                return m_r
            return s_r
        return _get

    def _factory(**kwargs):
        client = AsyncMock()
        client.get = _make_get()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    return _factory


@pytest.mark.asyncio
async def test_fetch_margin_trading_success():
    """融資+融券合併為每日一列，最新在前，latest 正確。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _margin_client_router(_margin_payload(), _short_payload())
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_margin_trading("2330", recent=10)

    assert result["symbol"] == "2330"
    assert result["stock_name"] == "台積電"
    days = result["recent_days"]
    assert days[0]["date"] == "20260911"  # 最新在前
    assert days[0]["融資餘額"] == 36728.0
    assert days[0]["融券餘額"] == 50.0
    assert result["latest"]["date"] == "20260911"


@pytest.mark.asyncio
async def test_fetch_margin_trading_short_only_missing_ok():
    """融券端點掛掉 → 仍回融資段（best-effort）。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _margin_client_router(_margin_payload(), None)
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_margin_trading("2330")

    assert result["recent_days"][0]["融資餘額"] == 36728.0
    assert result["recent_days"][0]["融券餘額"] is None


@pytest.mark.asyncio
async def test_fetch_margin_trading_all_empty():
    """兩端點全掛 → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _margin_client_router(None, None)
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_margin_trading("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_margin_trading_no_token():
    """登入失敗 → error dict。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_margin_trading("2330")
    assert "error" in result


# --- fetch_holder_structure() tests (A17 籌碼結構) ---


def _holdings_payload():
    """Mimic cronjob MajorInvestorsHoldings: list + column_title（最新在前）。"""
    return {
        "data": {
            "stock_name": "台積電",
            "column_title": [
                {"row_title_center": "年度/月份"},
                {"ua70028_cp": "外資持股比率"},
                {"raw70040": "董監持股比率"},
                {"ua70019_cp": "400張以上持股比率"},
            ],
            "data": [
                {"row_title_center": 202609, "ua70028_cp": 13.22, "ua70019_cp": 55.47},  # 最新月缺董監
                {"row_title_center": 202501, "ua70028_cp": 17.81, "raw70040": 7.77, "ua70019_cp": 57.68},
            ],
        }
    }


def _shstat_payload():
    """Mimic cronjob ShareHoldersStatistics: list + column_title。"""
    return {
        "data": {
            "column_title": [
                {"row_title_center": "年度/月份"},
                {"ua70041_cp": "總股東人數(人)"},
                {"ua70045_cp": "平均持有張數/人"},
                {"ua70019_cp": "400張以上持股比率(%)"},
                {"ua70020_cp": "1000張以上持股比率(%)"},
            ],
            "data": [
                {"row_title_center": 202609, "ua70041_cp": 510517, "ua70045_cp": 14.74,
                 "ua70019_cp": 55.47, "ua70020_cp": 51.55},
                {"row_title_center": 202501, "ua70041_cp": 502770, "ua70045_cp": 15.02,
                 "ua70019_cp": 57.68, "ua70020_cp": 53.86},
            ],
        }
    }


def _holder_client_router(holdings_payload, shstat_payload):
    def _resp(p):
        return _make_httpx_response(200, p) if p is not None else _make_httpx_response(500, {})

    h_r, s_r = _resp(holdings_payload), _resp(shstat_payload)

    def _make_get():
        async def _get(url, *args, **kwargs):
            if "MajorInvestorsHoldings" in url:
                return h_r
            return s_r
        return _get

    def _factory(**kwargs):
        client = AsyncMock()
        client.get = _make_get()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    return _factory


@pytest.mark.asyncio
async def test_fetch_holder_structure_success():
    """兩段解碼 column_title、最新在前、latest 正確；容忍缺欄位。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _holder_client_router(_holdings_payload(), _shstat_payload())
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_holder_structure("2330", recent=6)

    assert result["symbol"] == "2330"
    assert result["stock_name"] == "台積電"
    h0 = result["holdings"][0]
    assert h0["period"] == 202609
    assert h0["外資持股比率"] == 13.22
    assert "董監持股比率" not in h0  # 最新月缺，容錯不報錯
    s0 = result["shareholders"][0]
    assert s0["總股東人數(人)"] == 510517
    assert s0["1000張以上持股比率(%)"] == 51.55
    assert result["latest"]["holdings"]["外資持股比率"] == 13.22
    assert result["latest"]["shareholders"]["總股東人數(人)"] == 510517


@pytest.mark.asyncio
async def test_fetch_holder_structure_shstat_only():
    """持股比率端點掛掉 → 仍回股東結構段。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _holder_client_router(None, _shstat_payload())
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_holder_structure("2330")

    assert "shareholders" in result
    assert "holdings" not in result


@pytest.mark.asyncio
async def test_fetch_holder_structure_all_empty():
    """兩段全掛 → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _holder_client_router(None, None)
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_holder_structure("9999")

    assert "error" in result
    assert "9999" in result["error"]


@pytest.mark.asyncio
async def test_fetch_holder_structure_no_token():
    """登入失敗 → error dict。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_holder_structure("2330")
    assert "error" in result


# --- fetch_ai_chat() tests (A18 AI 知識庫問答, SSE) ---


def _sse_lines():
    """模擬 chat SSE：含 <think> 思考塊 + 正文 chunk。"""
    return [
        'data: {"type":"content","data":{"chunk":"<think>"}}',
        'data: {"type":"content","data":{"chunk":"內部推理"}}',
        'data: {"type":"content","data":{"chunk":"</think>"}}',
        'data: {"type":"content","data":{"chunk":"台積電近況"}}',
        'data: {"type":"content","data":{"chunk":"營收創高。"}}',
        'data: {"type":"other","data":{"chunk":"忽略"}}',
        "",
        "event: done",
    ]


def _mock_stream_client(lines, status_code=200):
    """Build a mock AsyncClient whose .stream() yields an SSE response."""
    class _Resp:
        def __init__(self):
            self.status_code = status_code

        async def aiter_lines(self):
            for ln in lines:
                yield ln

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *a):
            return False

    def _factory(**kwargs):
        client = MagicMock()
        client.stream = MagicMock(return_value=_StreamCtx())
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    return _factory


@pytest.mark.asyncio
async def test_fetch_ai_chat_success():
    """SSE 逐塊組成完整答案，<think> 思考塊被濾除。"""
    _auth.access_token = "tok"
    _auth.refresh_token = "ref"

    factory = _mock_stream_client(_sse_lines())
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_ai_chat("2330", "近況如何", "general")

    assert result["symbol"] == "2330"
    assert result["knowledge_base"] == "ua_ai_insight_general"
    assert result["answer"] == "台積電近況營收創高。"
    assert "<think>" not in result["answer"]


@pytest.mark.asyncio
async def test_fetch_ai_chat_kb_alias():
    """知識庫別名 teacher → 完整 api_name。"""
    _auth.access_token = "tok"
    factory = _mock_stream_client(_sse_lines())
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_ai_chat("2330", "怎麼估值", "teacher")
    assert result["knowledge_base"] == "ua_ai_insight_teacher"


@pytest.mark.asyncio
async def test_fetch_ai_chat_empty_question():
    """空問題 → error（不需登入）。"""
    result = await fetch_ai_chat("2330", "  ")
    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_ai_chat_http_error():
    """非 200 → error dict。"""
    _auth.access_token = "tok"
    _auth.refresh_token = None
    factory = _mock_stream_client([], status_code=500)
    with patch("httpx.AsyncClient", side_effect=factory):
        result = await fetch_ai_chat("2330", "近況")
    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_ai_chat_no_token():
    """登入失敗 → error dict。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_ai_chat("2330", "近況")
    assert "error" in result


# --- fetch_company_keywords() tests (A19 批次雷達) ---


@pytest.mark.asyncio
async def test_fetch_company_keywords_success(tmp_path):
    """回傳落地成檔、只回路徑 + 每類筆數摘要（不整包回傳）。"""
    _auth.access_token = "tok"
    payload = {"status": "OK", "data": {"transcript": [1, 2, 3], "company_info": {"a": 1}}}
    resp = _make_httpx_response(200, payload)
    resp.content = json.dumps(payload).encode()

    with patch("httpx.AsyncClient", return_value=_mock_async_client(resp)), \
         patch("tools.uanalyze.RADAR_OUTPUT_DIR", str(tmp_path)):
        result = await fetch_company_keywords("台積電", "transcript,company_info")

    assert result["keyword"] == "台積電"
    assert result["summary"] == {"transcript": 3, "company_info": 1}
    assert result["file"].endswith(".json")
    import os as _os
    assert _os.path.exists(result["file"])


@pytest.mark.asyncio
async def test_fetch_company_keywords_empty_keyword():
    """空關鍵字 → error。"""
    result = await fetch_company_keywords("")
    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_company_keywords_http_error(tmp_path):
    """非 200 → error dict。"""
    _auth.access_token = "tok"
    resp = _make_httpx_response(500, {})
    resp.content = b""
    with patch("httpx.AsyncClient", return_value=_mock_async_client(resp)), \
         patch("tools.uanalyze.RADAR_OUTPUT_DIR", str(tmp_path)):
        result = await fetch_company_keywords("台積電")
    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_company_keywords_no_token():
    """登入失敗 → error dict。"""
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        result = await fetch_company_keywords("台積電")
    assert "error" in result
