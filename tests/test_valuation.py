"""Tests for tools/valuation.py."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.valuation import (
    eps_momentum,
    lohas,
    mean_reversion,
    pe_river,
    percentile_rank,
    quartile,
    std_bands,
    target_summary,
)


# ── 數學核心（純函式）─────────────────────────────────────

def test_mean_reversion_upward_trend():
    prices = list(range(100, 200))  # 穩定上升
    r = mean_reversion(prices)
    assert r["current_price"] == 199.0
    assert "bands" in r
    assert "趨勢價位" in r["bands"]
    # 機率相加 ≈ 100
    assert r["up_prob_pct"] + r["down_prob_pct"] == pytest.approx(100.0, abs=0.01)


def test_mean_reversion_insufficient():
    assert mean_reversion([1]) == {}
    assert mean_reversion([]) == {}


def test_quartile():
    q = quartile([10, 20, 30, 40, 50])
    assert q["q50"] == 30.0
    assert q["mean"] == 30.0


def test_std_bands_ordering():
    b = std_bands([10, 12, 14, 16, 18, 20])
    assert b["TL+3SD"] > b["TL"] > b["TL-3SD"]


def test_percentile_rank():
    assert percentile_rank([10, 20, 30, 40, 50], 30) == 40.0
    assert percentile_rank([], 10) == 50.0  # 無資料回中位


# ── 估值 function（mock raw 工具）──────────────────────────

@pytest.mark.asyncio
async def test_lohas_uses_fugle():
    candles = [{"close": float(100 + i)} for i in range(100)]
    with patch("tools.valuation.fugle.fetch_historical_candles",
               new=AsyncMock(return_value={"data": candles})):
        res = await lohas("2330", years=1.0)
    assert res["symbol"] == "2330"
    assert res["n_points"] == 100
    assert "bands" in res


@pytest.mark.asyncio
async def test_lohas_fallback_cnyes():
    """Fugle 無資料 → 退回 CNYES。"""
    cnyes_candles = [{"close": float(100 + i)} for i in range(80)]
    with (
        patch("tools.valuation.fugle.fetch_historical_candles",
              new=AsyncMock(return_value={"error": "no key"})),
        patch("tools.valuation.cnyes.fetch_history",
              new=AsyncMock(return_value={"candles": cnyes_candles})),
    ):
        res = await lohas("2330")
    assert res["n_points"] == 80


@pytest.mark.asyncio
async def test_lohas_insufficient():
    with patch("tools.valuation.fugle.fetch_historical_candles",
               new=AsyncMock(return_value={"data": [{"close": 100}]})):
        with patch("tools.valuation.cnyes.fetch_history",
                   new=AsyncMock(return_value={"candles": []})):
            res = await lohas("2330")
    assert "error" in res


@pytest.mark.asyncio
async def test_pe_river():
    rows = [{"PER": 15 + (i % 5), "PBR": 2.0} for i in range(50)]
    with patch("tools.valuation.finmind.fetch_per_pbr",
               return_value={"data": rows}):
        res = await pe_river("2330")
    assert res["metric"] == "PER"
    assert res["n_points"] == 50
    assert "quartile" in res
    assert "percentile" in res


@pytest.mark.asyncio
async def test_pe_river_no_token():
    with patch("tools.valuation.finmind.fetch_per_pbr",
               return_value={"error": "no token"}):
        res = await pe_river("2330")
    assert "error" in res


@pytest.mark.asyncio
async def test_eps_momentum_signal():
    eps_data = {"data": [
        {"financial_year": 2026, "eps_median": 100, "up": 37, "down": 0, "num_est": 44, "rate_date": "2026-08-31"},
        {"financial_year": 2027, "eps_median": 140, "up": 37, "down": 0, "num_est": 44, "rate_date": "2026-08-31"},
    ]}
    with patch("tools.valuation.cnyes.fetch_estimate_eps",
               new=AsyncMock(return_value=eps_data)):
        res = await eps_momentum("2330")
    assert res["signal"] == "分析師偏上修"
    assert res["yoy_growth_pct"] == [40.0]  # (140-100)/100*100


@pytest.mark.asyncio
async def test_target_summary_merges_sources():
    with (
        patch("tools.valuation.cnyes.fetch_target_price",
              new=AsyncMock(return_value={"target_mean": 3232, "last": 2410, "upside_pct": 34.1, "num_est": 34,
                                          "target_high": 4200, "target_low": 2700})),
        patch("tools.valuation.yfinance_data.fetch_target",
              new=AsyncMock(return_value={"targetMeanPrice": 3229, "currentPrice": 2410,
                                          "numberOfAnalystOpinions": 33, "recommendationKey": "strong_buy",
                                          "targetHighPrice": 4200, "targetLowPrice": 2650, "upside_pct": 34.0})),
    ):
        res = await target_summary("2330")
    assert "cnyes" in res["sources"]
    assert "yahoo" in res["sources"]
    assert res["sources"]["cnyes"]["target_mean"] == 3232
    assert res["sources"]["yahoo"]["recommendation"] == "strong_buy"


@pytest.mark.asyncio
async def test_target_summary_all_fail():
    with (
        patch("tools.valuation.cnyes.fetch_target_price",
              new=AsyncMock(return_value={"error": "x"})),
        patch("tools.valuation.yfinance_data.fetch_target",
              new=AsyncMock(return_value={"error": "y"})),
    ):
        res = await target_summary("9999")
    assert "error" in res
