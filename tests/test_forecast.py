"""Tests for tools/analysis/forecast.py — 前瞻預估整理（call raw）。"""

from unittest.mock import AsyncMock, patch

import pytest

from tools.analysis.forecast import forecast_route, smart_estimate


@pytest.mark.asyncio
async def test_smart_estimate_success():
    """raw 回 {指標: 3欄 raw}，整理成逐年 平均/最低/最高。"""
    raw = {
        "EPS": {
            "refinitiv_1": {"ChineseAccount": "每股盈餘EPS平均值", "Data": {"2027(f)": 150.0, "2028(f)": 181.38}},
            "refinitiv_2": {"ChineseAccount": "每股盈餘EPS最低值", "Data": {"2027(f)": 140.0, "2028(f)": 149.76}},
            "refinitiv_3": {"ChineseAccount": "每股盈餘EPS最高值", "Data": {"2027(f)": 160.0, "2028(f)": 210.6}},
        }
    }
    with patch("tools.analysis.forecast.raw_uanalyze.fetch_raw_smart_estimate",
               new=AsyncMock(return_value=raw)):
        r = await smart_estimate("2330")
    assert r["symbol"] == "2330"
    last = r["estimates"]["EPS"][-1]
    assert last["year"] == "2028(f)"
    assert last["平均"] == 181.38 and last["最低"] == 149.76 and last["最高"] == 210.6


@pytest.mark.asyncio
async def test_smart_estimate_empty_string_to_none():
    raw = {"EPS": {
        "refinitiv_1": {"ChineseAccount": "平均值", "Data": {"2029(f)": ""}},
        "refinitiv_2": {"ChineseAccount": "最低值", "Data": {"2029(f)": ""}},
        "refinitiv_3": {"ChineseAccount": "最高值", "Data": {"2029(f)": ""}},
    }}
    with patch("tools.analysis.forecast.raw_uanalyze.fetch_raw_smart_estimate",
               new=AsyncMock(return_value=raw)):
        r = await smart_estimate("2330")
    assert r["estimates"]["EPS"][-1]["平均"] is None


@pytest.mark.asyncio
async def test_smart_estimate_raw_error():
    with patch("tools.analysis.forecast.raw_uanalyze.fetch_raw_smart_estimate",
               new=AsyncMock(return_value={"error": "登入失敗"})):
        r = await smart_estimate("2330")
    assert "error" in r


@pytest.mark.asyncio
async def test_forecast_route_success():
    eps = {"ua50224_cp": {"ChineseAccount": "未來五季EPS預估路徑",
                          "Data": {"2027Q2(f)": 34.19, "2027Q3(f)": 38.01}}}
    margin = {"error": "x"}
    rating = {
        "ua70232_cp": {"ChineseAccount": "樂觀評等佔比", "Data": {"202609": 88.18}},
        "ua70233_cp": {"ChineseAccount": "中立評等佔比", "Data": {"202609": 11.82}},
        "ua70234_cp": {"ChineseAccount": "悲觀評等佔比", "Data": {"202609": 0.0}},
        "ua70001_cp": {"ChineseAccount": "月收盤價", "Data": {"202609": 2410.0}},
    }
    with patch("tools.analysis.forecast.raw_uanalyze.fetch_raw_eps_route",
               new=AsyncMock(return_value=eps)), \
         patch("tools.analysis.forecast.raw_uanalyze.fetch_raw_margin_route",
               new=AsyncMock(return_value=margin)), \
         patch("tools.analysis.forecast.raw_uanalyze.fetch_raw_rating_trend",
               new=AsyncMock(return_value=rating)):
        r = await forecast_route("2330")
    assert r["route"]["未來五季EPS預估路徑"][-1] == {"period": "2027Q3(f)", "value": 38.01}
    assert r["rating_trend"][-1]["樂觀"] == 88.18


@pytest.mark.asyncio
async def test_forecast_route_all_error():
    with patch("tools.analysis.forecast.raw_uanalyze.fetch_raw_eps_route",
               new=AsyncMock(return_value={"error": "x"})), \
         patch("tools.analysis.forecast.raw_uanalyze.fetch_raw_margin_route",
               new=AsyncMock(return_value={"error": "x"})), \
         patch("tools.analysis.forecast.raw_uanalyze.fetch_raw_rating_trend",
               new=AsyncMock(return_value={"error": "x"})):
        r = await forecast_route("9999")
    assert "error" in r
