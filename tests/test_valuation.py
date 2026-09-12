"""Tests for tools/analysis/valuation.py."""

from unittest.mock import AsyncMock, patch

import pytest

from tools.analysis.valuation import (
    _compute_dcf,
    dcf_valuation,
    eps_momentum,
    lohas,
    mean_reversion,
    pe_pb_band,
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
    with patch("tools.analysis.valuation.fugle.fetch_historical_candles",
               new=AsyncMock(return_value={"data": candles})):
        res = await lohas("2330", years=1.0)
    assert res["symbol"] == "2330"
    assert res["n_points"] == 100
    assert "bands" in res


@pytest.mark.asyncio
async def test_lohas_insufficient():
    with patch("tools.analysis.valuation.fugle.fetch_historical_candles",
               new=AsyncMock(return_value={"data": [{"close": 100}]})):
        res = await lohas("2330")
    assert "error" in res


@pytest.mark.asyncio
async def test_pe_river():
    rows = [{"PER": 15 + (i % 5), "PBR": 2.0} for i in range(50)]
    with patch("tools.analysis.valuation.finmind.fetch_per_pbr",
               return_value={"data": rows}):
        res = await pe_river("2330")
    assert res["metric"] == "PER"
    assert res["n_points"] == 50
    assert "quartile" in res
    assert "percentile" in res


@pytest.mark.asyncio
async def test_pe_river_no_token():
    with patch("tools.analysis.valuation.finmind.fetch_per_pbr",
               return_value={"error": "no token"}):
        res = await pe_river("2330")
    assert "error" in res


@pytest.mark.asyncio
async def test_eps_momentum_signal():
    eps_data = {"data": [
        {"financial_year": 2026, "eps_median": 100, "up": 37, "down": 0, "num_est": 44, "rate_date": "2026-08-31"},
        {"financial_year": 2027, "eps_median": 140, "up": 37, "down": 0, "num_est": 44, "rate_date": "2026-08-31"},
    ]}
    with patch("tools.analysis.valuation.cnyes.fetch_estimate_eps",
               new=AsyncMock(return_value=eps_data)):
        res = await eps_momentum("2330")
    assert res["signal"] == "分析師偏上修"
    assert res["yoy_growth_pct"] == [40.0]  # (140-100)/100*100


@pytest.mark.asyncio
async def test_target_summary_merges_sources():
    with (
        patch("tools.analysis.valuation.cnyes.fetch_target_price",
              new=AsyncMock(return_value={"target_mean": 3232, "last": 2410, "upside_pct": 34.1, "num_est": 34,
                                          "target_high": 4200, "target_low": 2700})),
        patch("tools.analysis.valuation.yfinance_data.fetch_target",
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
        patch("tools.analysis.valuation.cnyes.fetch_target_price",
              new=AsyncMock(return_value={"error": "x"})),
        patch("tools.analysis.valuation.yfinance_data.fetch_target",
              new=AsyncMock(return_value={"error": "y"})),
    ):
        res = await target_summary("9999")
    assert "error" in res


# ── DCF 純數學核心（_compute_dcf 迴歸鎖）─────────────────────────────


def test_compute_dcf_regression_base_year_2024():
    """Regression lock：固定 base_year + 2330-shaped 輸入 → 精確輸出。"""
    eps_hist = {2023: 32.34, 2024: 45.25, 2025: 66.26}
    eps_fore = {2026: 109.58, 2027: 151.15, 2028: 190.09, 2029: 239.09, 2030: 293.74}
    (base_ttm, v_2025, v_2026E, v_2027E, far_fore_yr, far_fore_eps,
     confidence_level, intrinsic_val) = _compute_dcf(
        eps_hist, eps_fore, "+0.1%", 0.1, current_month=8, base_year=2025)
    assert v_2025 == 66.26
    assert v_2026E == 109.58
    assert v_2027E == 151.15
    assert far_fore_yr == 2030
    assert far_fore_eps == 293.74
    assert confidence_level == "高 (法人完全直連 N=5)"
    assert round(base_ttm, 2) == 91.57
    assert intrinsic_val == 3101.0


def test_compute_dcf_high_growth_discount_confidence():
    """N=2 且 marginal YoY>50% → 信心度打折路徑。"""
    eps_hist = {2024: 5.0, 2025: 8.0}
    eps_fore = {2026: 20.0, 2027: 40.0}
    (*_, far_fore_yr, _far_eps, confidence_level, intrinsic_val) = _compute_dcf(
        eps_hist, eps_fore, "+5.0%", 5.0, current_month=8, base_year=2025)
    assert far_fore_yr == 2027
    assert confidence_level == "⚠️ 低 (N≤2極端外推打折)"
    assert intrinsic_val == 512.55


def test_compute_dcf_no_revenue_multiplier():
    """rev_gap_pct_str == '-' → 乘數中性(1.0)；base_ttm 純加權。"""
    eps_hist = {2024: 10.0, 2025: 10.0}
    eps_fore = {2026: 10.0, 2027: 10.0, 2028: 10.0}
    base_ttm, *_ = _compute_dcf(eps_hist, eps_fore, "-", 0.0, current_month=8, base_year=2025)
    assert round(base_ttm, 6) == 10.0


# ── dcf_valuation（call raw，mock）────────────────────────────────────


@pytest.mark.asyncio
async def test_dcf_valuation_success():
    """call raw eps_revenue_consensus + revenue_tracking，組成 DCF 結果。"""
    eps_raw = {"ua50187_cp": {"Data": {
        "2024": 45.25, "2025": 66.26,
        "2026(f)": 109.58, "2027(f)": 151.15, "2028(f)": 190.09,
        "2029(f)": 239.09, "2030(f)": 293.74,
    }}}
    rev_raw = {"ua70306_cp": {"Data": {"202607": 0.1}}}
    with patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_eps_revenue_consensus",
               new=AsyncMock(return_value=eps_raw)), \
         patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_revenue_tracking",
               new=AsyncMock(return_value=rev_raw)):
        r = await dcf_valuation("2330")
    assert r["symbol"] == "2330"
    assert "每股合理內在價值" in r
    assert "信心度" in r


@pytest.mark.asyncio
async def test_dcf_valuation_insufficient_eps():
    """EPS 只有歷史無預估 → 資料不足 error。"""
    eps_raw = {"ua50187_cp": {"Data": {"2025": 66.26}}}  # 無 (f)
    with patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_eps_revenue_consensus",
               new=AsyncMock(return_value=eps_raw)), \
         patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_revenue_tracking",
               new=AsyncMock(return_value={"error": "x"})):
        r = await dcf_valuation("2330")
    assert "error" in r


@pytest.mark.asyncio
async def test_dcf_valuation_raw_error():
    """raw 取數 error → 傳遞 error。"""
    with patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_eps_revenue_consensus",
               new=AsyncMock(return_value={"error": "登入失敗"})), \
         patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_revenue_tracking",
               new=AsyncMock(return_value={"error": "x"})):
        r = await dcf_valuation("2330")
    assert "error" in r


# ── pe_pb_band（call raw，mock）───────────────────────────────────────


@pytest.mark.asyncio
async def test_pe_pb_band_success():
    per_raw = {"ua70002_cp": {"ChineseAccount": "本益比",
                              "Data": {f"2020{m:02d}": 15 + m for m in range(1, 13)}}}
    pbr_raw = {"ua70009_cp": {"ChineseAccount": "股價淨值比",
                              "Data": {f"2020{m:02d}": 3 + m * 0.1 for m in range(1, 13)}}}
    band_raw = {"refdata": {"peer_pe_median": 18.5}}
    with patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_historical_per",
               new=AsyncMock(return_value=per_raw)), \
         patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_historical_pbr",
               new=AsyncMock(return_value=pbr_raw)), \
         patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_pe_band",
               new=AsyncMock(return_value=band_raw)):
        r = await pe_pb_band("2330")
    assert r["symbol"] == "2330"
    assert "pe" in r and "pb" in r
    assert r["pe"]["peer_median"] == 18.5
    assert "percentile_in_history" in r["pe"]


@pytest.mark.asyncio
async def test_pe_pb_band_all_error():
    with patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_historical_per",
               new=AsyncMock(return_value={"error": "x"})), \
         patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_historical_pbr",
               new=AsyncMock(return_value={"error": "x"})), \
         patch("tools.analysis.valuation.raw_uanalyze.fetch_raw_pe_band",
               new=AsyncMock(return_value={"error": "x"})):
        r = await pe_pb_band("9999")
    assert "error" in r
