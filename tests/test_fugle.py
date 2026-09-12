"""Tests for tools/raw/fugle.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.raw.fugle import fetch_historical_candles, fetch_quote, fetch_stats, fetch_ticker


def _mock_client(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_fetch_quote_success():
    payload = {"symbol": "2330", "name": "台積電", "closePrice": 2410}
    with (
        patch("tools.raw.fugle._get_key", return_value="k"),
        patch("httpx.AsyncClient", return_value=_mock_client(payload)),
    ):
        res = await fetch_quote("2330")
    assert res["closePrice"] == 2410
    assert res["name"] == "台積電"


@pytest.mark.asyncio
async def test_fetch_no_key():
    with patch("tools.raw.fugle._get_key", return_value=None):
        res = await fetch_quote("2330")
    assert "error" in res
    assert "FUGLE_API_KEY" in res["error"]


@pytest.mark.asyncio
async def test_fetch_http_error():
    with (
        patch("tools.raw.fugle._get_key", return_value="k"),
        patch("httpx.AsyncClient", return_value=_mock_client({}, status=403)),
    ):
        res = await fetch_ticker("2330")
    assert "error" in res
    assert "403" in res["error"]


@pytest.mark.asyncio
async def test_fetch_stats_success():
    payload = {"symbol": "2330", "week52High": 2500, "week52Low": 800}
    with (
        patch("tools.raw.fugle._get_key", return_value="k"),
        patch("httpx.AsyncClient", return_value=_mock_client(payload)),
    ):
        res = await fetch_stats("2330")
    assert res["week52High"] == 2500


@pytest.mark.asyncio
async def test_fetch_historical_candles_params():
    """確認歷史K線帶正確 query params，且回傳合併後含日期的資料。"""
    captured = {}

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"symbol": "2330", "data": [{"date": "2026-01-02", "close": 100}]}
    client = AsyncMock()

    async def _get(url, headers=None, params=None):
        captured["params"] = params
        return resp

    client.get = _get
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("tools.raw.fugle._get_key", return_value="k"),
        patch("httpx.AsyncClient", return_value=client),
    ):
        res = await fetch_historical_candles("2330", days=30)
    assert captured["params"]["timeframe"] == "D"
    assert captured["params"]["sort"] == "asc"
    assert res["data"][0]["close"] == 100


@pytest.mark.asyncio
async def test_fetch_historical_candles_multi_segment():
    """超過一年 → 分段查詢，各段結果依日期去重合併。"""
    # 依 from 參數回不同日期的資料，模擬多段
    def _resp_for(params):
        frm = params["from"]
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"symbol": "2330", "data": [{"date": frm, "close": 100}]}
        return resp

    call_count = {"n": 0}
    client = AsyncMock()

    async def _get(url, headers=None, params=None):
        call_count["n"] += 1
        return _resp_for(params)

    client.get = _get
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("tools.raw.fugle._get_key", return_value="k"),
        patch("httpx.AsyncClient", return_value=client),
    ):
        res = await fetch_historical_candles("2330", days=1277)  # ~3.5 年
    # 應分成多段（1277 / 360 ≈ 4 段）
    assert call_count["n"] >= 3
    # 各段日期不同 → 合併後多筆
    assert len(res["data"]) >= 3
