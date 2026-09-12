"""Tests for tools/raw/uanalyze.py — 純資料抓取層（一端點一 fetcher）。

策略：raw fetcher 的共同形狀是「ensure_token → 打一個端點 → 回原始 data / {"error"}」。
測「每種認證路徑（cronjob / gidp / jwt）的代表 fetcher」+「特殊結構（並行、POST、雙模式、
巢狀）」+「共同分支（成功 / 空 / HTTP 錯誤 / 無憑證）」，而非每支都重測相同骨架。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.raw.uanalyze import (
    _auth,
    fetch_raw_ai_chat,
    fetch_raw_company_keywords,
    fetch_raw_eps_revenue_consensus,
    fetch_raw_historical_per,
    fetch_raw_institutional_net,
    fetch_raw_report_summaries,
    fetch_raw_smart_estimate,
)


def _resp(status_code: int, json_data: dict):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    r.content = json.dumps(json_data).encode()
    return r


def _client(response):
    c = AsyncMock()
    c.get = AsyncMock(return_value=response)
    c.post = AsyncMock(return_value=response)
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=False)
    return c


@pytest.fixture(autouse=True)
def _reset_auth():
    _auth.access_token = None
    _auth.refresh_token = None
    _auth.token_type = None
    _auth.expires_in = None
    yield
    _auth.access_token = None


# ── cronjob 代表：historical_per（回 data.data dict）────────────────────────


@pytest.mark.asyncio
async def test_historical_per_success():
    _auth.access_token = "tok"
    payload = {"data": {"data": {"ua70002_cp": {"ChineseAccount": "本益比",
                                                "Data": {"202609": 27.9}}}}}
    with patch("httpx.AsyncClient", return_value=_client(_resp(200, payload))):
        r = await fetch_raw_historical_per("2330")
    assert r["ua70002_cp"]["ChineseAccount"] == "本益比"


@pytest.mark.asyncio
async def test_historical_per_empty():
    _auth.access_token = "tok"
    with patch("httpx.AsyncClient", return_value=_client(_resp(200, {"data": {"data": None}}))):
        r = await fetch_raw_historical_per("9999")
    assert "error" in r


@pytest.mark.asyncio
async def test_historical_per_http_error():
    _auth.access_token = "tok"
    with patch("httpx.AsyncClient", return_value=_client(_resp(500, {}))):
        r = await fetch_raw_historical_per("2330")
    assert "error" in r


@pytest.mark.asyncio
async def test_historical_per_no_token():
    with patch.dict("os.environ", {"UANALYZE_EMAIL": "", "UANALYZE_PASSWORD": ""}):
        r = await fetch_raw_historical_per("2330")
    assert "error" in r


@pytest.mark.asyncio
async def test_historical_per_empty_symbol():
    r = await fetch_raw_historical_per("  ")
    assert "error" in r


# ── cronjob 回整包 data（含 column_title）：institutional_net ─────────────────


@pytest.mark.asyncio
async def test_institutional_net_returns_full_data():
    _auth.access_token = "tok"
    payload = {"data": {"data": [{"raw80050": 1}], "column_title": [{"raw80050": "外資"}]}}
    with patch("httpx.AsyncClient", return_value=_client(_resp(200, payload))):
        r = await fetch_raw_institutional_net("2330")
    # 回整包 data（含 column_title），不只 data.data
    assert "column_title" in r and "data" in r


# ── gidp 代表：eps_revenue_consensus ────────────────────────────────────────


@pytest.mark.asyncio
async def test_eps_revenue_consensus_success():
    _auth.access_token = "tok"
    payload = {"data": {"data": {"ua50187_cp": {"Data": {"2026(f)": 60.0}}}}}
    with patch("httpx.AsyncClient", return_value=_client(_resp(200, payload))):
        r = await fetch_raw_eps_revenue_consensus("2330")
    assert "ua50187_cp" in r


# ── report_summaries 雙模式（單股 / 全站）──────────────────────────────────


@pytest.mark.asyncio
async def test_report_summaries_all_site():
    """不帶 symbol → 全站模式（推播用），params 無 stock。"""
    _auth.access_token = "tok"
    client = _client(_resp(200, {"status": "OK", "data": [{"id": 1}]}))
    with patch("httpx.AsyncClient", return_value=client):
        r = await fetch_raw_report_summaries()
    assert r["status"] == "OK"
    # 確認全站模式沒帶 stock 參數
    _, kwargs = client.get.call_args
    assert "stock" not in kwargs.get("params", {})


@pytest.mark.asyncio
async def test_report_summaries_single_stock():
    """帶 symbol → params 有 stock。"""
    _auth.access_token = "tok"
    client = _client(_resp(200, {"status": "OK", "data": []}))
    with patch("httpx.AsyncClient", return_value=client):
        await fetch_raw_report_summaries("2330")
    _, kwargs = client.get.call_args
    assert kwargs["params"]["stock"] == "2330"


# ── smart_estimate 並行 8 端點 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_smart_estimate_parallel():
    _auth.access_token = "tok"
    # 所有端點回同一結構（測並行組裝；只要非空就收）
    payload = {"data": {"data": {"refinitiv_1": {"ChineseAccount": "平均", "Data": {"2026(f)": 1.0}}}}}
    with patch("httpx.AsyncClient", return_value=_client(_resp(200, payload))):
        r = await fetch_raw_smart_estimate("2330")
    # 8 個指標中文名都應在
    assert "EPS" in r and "營收" in r and "每股股息" in r


@pytest.mark.asyncio
async def test_smart_estimate_all_empty():
    _auth.access_token = "tok"
    with patch("httpx.AsyncClient", return_value=_client(_resp(200, {"data": {"data": {}}}))):
        r = await fetch_raw_smart_estimate("9999")
    assert "error" in r


# ── ai_chat（SSE 串流；回原始 chunks，不濾 <think>）──────────────────────────


def _stream_client(lines, status=200):
    class _R:
        status_code = status
        async def aiter_lines(self):
            for ln in lines:
                yield ln
    class _Ctx:
        async def __aenter__(self):
            return _R()
        async def __aexit__(self, *a):
            return False
    def factory(**kw):
        c = MagicMock()
        c.stream = MagicMock(return_value=_Ctx())
        c.__aenter__ = AsyncMock(return_value=c)
        c.__aexit__ = AsyncMock(return_value=False)
        return c
    return factory


@pytest.mark.asyncio
async def test_ai_chat_returns_raw_chunks():
    """raw 層回原始 answer（含 <think>，不濾——濾除是消費者的事）。"""
    _auth.access_token = "tok"
    lines = [
        'data: {"type":"content","data":{"chunk":"<think>想"}}',
        'data: {"type":"content","data":{"chunk":"</think>答案"}}',
    ]
    with patch("httpx.AsyncClient", side_effect=_stream_client(lines)):
        r = await fetch_raw_ai_chat("2330", "近況", "knowledge")
    assert r["knowledge_base"] == "ua_ai_insight_knowledge"
    assert r["answer"] == "<think>想</think>答案"  # 原始，未濾
    assert r["chunks"] == ["<think>想", "</think>答案"]


@pytest.mark.asyncio
async def test_ai_chat_empty_question():
    r = await fetch_raw_ai_chat("2330", "  ")
    assert "error" in r


# ── company_keywords（POST multipart；回原始 payload 不落地）──────────────────


@pytest.mark.asyncio
async def test_company_keywords_returns_raw_payload():
    _auth.access_token = "tok"
    payload = {"status": "OK", "data": {"transcript": [1, 2]}}
    with patch("httpx.AsyncClient", return_value=_client(_resp(200, payload))):
        r = await fetch_raw_company_keywords("台積電", "transcript")
    # raw 層回原始 payload（不落地、不摘要）
    assert r["data"]["transcript"] == [1, 2]


@pytest.mark.asyncio
async def test_company_keywords_empty_keyword():
    r = await fetch_raw_company_keywords("")
    assert "error" in r
