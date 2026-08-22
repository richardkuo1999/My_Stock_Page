"""Tests for tools/uanalyze.py."""

import json
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.uanalyze import (
    UAnalyzeAuth,
    _auth,
    _request_with_auth,
    analyze,
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
    yield
    _auth.access_token = None
    _auth.refresh_token = None


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
