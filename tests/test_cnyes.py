"""Tests for tools/cnyes.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.cnyes import (
    _decode_quote,
    _to_sym,
    fetch_estimate_eps,
    fetch_history,
    fetch_quote,
    fetch_target_price,
)


def _mock_client(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def test_to_sym():
    assert _to_sym("2330") == "TWS:2330:STOCK"
    assert _to_sym("6488") == "TWS:6488:STOCK"  # 4 碼上市
    assert _to_sym("00878") == "OTC:00878:STOCK"  # 5 碼
    assert _to_sym("TWS:2330:STOCK") == "TWS:2330:STOCK"  # 已含前綴


def test_decode_quote():
    raw = {"6": 2410.0, "11": 20.0, "56": 0.84, "200009": "台積電", "999999": "x"}
    out = _decode_quote(raw)
    assert out["close"] == 2410.0
    assert out["change"] == 20.0
    assert out["change_pct"] == 0.84
    assert out["name"] == "台積電"
    assert out["999999"] == "x"  # 未知代碼保留


@pytest.mark.asyncio
async def test_fetch_estimate_eps_success():
    payload = {"statusCode": 200, "message": "OK", "data": [
        {"financialYear": 2026, "rateDate": "2026-08-31", "feMean": 107.77,
         "feMedian": 108.05, "feHigh": 113.38, "feLow": 98.4, "numEst": 44,
         "feUp": 37, "feDown": 0, "feStdDev": 2.96, "currency": "TWD"},
    ]}
    with patch("httpx.AsyncClient", return_value=_mock_client(payload)):
        res = await fetch_estimate_eps("2330")
    assert res["symbol"] == "2330"
    assert res["data"][0]["financial_year"] == 2026
    assert res["data"][0]["eps_median"] == 108.05
    assert res["data"][0]["num_est"] == 44


@pytest.mark.asyncio
async def test_fetch_estimate_eps_empty():
    with patch("httpx.AsyncClient", return_value=_mock_client({"statusCode": 200, "data": []})):
        res = await fetch_estimate_eps("9999")
    assert "error" in res


@pytest.mark.asyncio
async def test_fetch_target_price_computes_upside():
    payload = {"statusCode": 200, "data": {
        "chName": "台積電", "rateDate": "2026-08-26", "feMean": 3232.0,
        "feMedian": 3175.0, "feHigh": 4200.0, "feLow": 2700.0,
        "feUp": 30, "feDown": 0, "feStdDev": 303.79, "numEst": 34,
        "last": 2410.0, "currency": "TWD"}}
    with patch("httpx.AsyncClient", return_value=_mock_client(payload)):
        res = await fetch_target_price("2330")
    assert res["target_mean"] == 3232.0
    assert res["last"] == 2410.0
    # upside = (3232-2410)/2410*100 ≈ 34.11
    assert res["upside_pct"] == pytest.approx(34.11, abs=0.1)


@pytest.mark.asyncio
async def test_fetch_quote_decodes():
    payload = {"statusCode": 200, "data": [{"6": 2410.0, "200009": "台積電", "56": 0.84}]}
    with patch("httpx.AsyncClient", return_value=_mock_client(payload)):
        res = await fetch_quote("2330")
    assert res["close"] == 2410.0
    assert res["name"] == "台積電"
    assert res["symbol_input"] == "2330"


@pytest.mark.asyncio
async def test_fetch_history_builds_candles():
    payload = {"statusCode": 200, "data": {
        "t": [1700000000, 1700086400], "o": [100, 101], "h": [105, 106],
        "l": [99, 100], "c": [104, 105], "v": [1000, 1100]}}
    with patch("httpx.AsyncClient", return_value=_mock_client(payload)):
        res = await fetch_history("2330", days=10)
    assert res["symbol"] == "2330"
    assert len(res["candles"]) == 2
    assert res["candles"][0]["close"] == 104
    assert res["candles"][1]["volume"] == 1100


@pytest.mark.asyncio
async def test_fetch_history_empty():
    payload = {"statusCode": 200, "data": {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}}
    with patch("httpx.AsyncClient", return_value=_mock_client(payload)):
        res = await fetch_history("9999")
    assert "error" in res
