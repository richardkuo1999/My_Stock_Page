"""Tests for tools/raw/yfinance_data.py."""

from unittest.mock import MagicMock, patch

import pytest

from tools.raw.yfinance_data import fetch_info, fetch_target


def _mock_yf_ticker(info):
    t = MagicMock()
    t.info = info
    return t


@pytest.mark.asyncio
async def test_fetch_info_resolves_tw():
    info = {"longName": "TSMC", "currentPrice": 2410.0, "sector": "Technology",
            "trailingPE": 28.0, "priceToBook": 9.7}
    with patch("yfinance.Ticker", return_value=_mock_yf_ticker(info)):
        res = await fetch_info("2330")
    assert res["resolved"] == "2330.TW"
    assert res["longName"] == "TSMC"
    assert res["trailingPE"] == 28.0


@pytest.mark.asyncio
async def test_fetch_info_fallback_two():
    """.TW 無 price → 退回 .TWO。"""
    def _ticker(sym):
        if sym == "2330.TW":
            return _mock_yf_ticker({})  # 無 price
        return _mock_yf_ticker({"currentPrice": 50.0, "longName": "OTC Co"})

    with patch("yfinance.Ticker", side_effect=_ticker):
        res = await fetch_info("2330")
    assert res["resolved"] == "2330.TWO"
    assert res["longName"] == "OTC Co"


@pytest.mark.asyncio
async def test_fetch_info_not_found():
    with patch("yfinance.Ticker", return_value=_mock_yf_ticker({})):
        res = await fetch_info("9999")
    assert "error" in res


@pytest.mark.asyncio
async def test_fetch_target_computes_upside():
    info = {"currentPrice": 2410.0, "targetMeanPrice": 3229.0,
            "targetHighPrice": 4200.0, "targetLowPrice": 2650.0,
            "numberOfAnalystOpinions": 33, "recommendationKey": "strong_buy"}
    with patch("yfinance.Ticker", return_value=_mock_yf_ticker(info)):
        res = await fetch_target("2330")
    assert res["targetMeanPrice"] == 3229.0
    assert res["numberOfAnalystOpinions"] == 33
    # upside = (3229-2410)/2410*100 ≈ 33.98
    assert res["upside_pct"] == pytest.approx(33.98, abs=0.1)
