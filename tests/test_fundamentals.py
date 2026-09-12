"""Tests for tools/analysis/fundamentals.py — 即時基本面（best-effort）。"""

from unittest.mock import AsyncMock, patch

import pytest

from tools.analysis.fundamentals import fetch_stock_fundamentals


@pytest.mark.asyncio
async def test_fundamentals_success():
    """WebStockInfo 挑欄位 + HistoricalPer 取最新本益比。"""
    web = {
        "ua1": {"ChineseAccount": "收盤價", "Data": 2410.0},
        "ua2": {"ChineseAccount": "當日漲跌幅", "Data": 1.5},
        "ua3": {"ChineseAccount": "月營收", "Data": "5148億"},
        "ua4": {"ChineseAccount": "股票分類", "Data": ["這是list會被跳過"]},
    }
    per = {"ua70002_cp": {"ChineseAccount": "本益比", "Data": {"202608": 27.5, "202609": 27.9}}}
    with patch("tools.analysis.fundamentals.raw_uanalyze.fetch_raw_web_stock_info",
               new=AsyncMock(return_value=web)), \
         patch("tools.analysis.fundamentals.raw_uanalyze.fetch_raw_historical_per",
               new=AsyncMock(return_value=per)):
        r = await fetch_stock_fundamentals("2330")
    assert r["收盤價"] == 2410.0
    assert r["當日漲跌幅(%)"] == 1.5
    assert r["最新月營收"] == "5148億"
    assert r["本益比"] == 27.9          # 取最新月
    assert "股票分類" not in r          # list 型跳過


@pytest.mark.asyncio
async def test_fundamentals_best_effort_returns_empty_on_error():
    """raw 回 error → best-effort 回 {}（不是 error dict）。"""
    with patch("tools.analysis.fundamentals.raw_uanalyze.fetch_raw_web_stock_info",
               new=AsyncMock(return_value={"error": "登入失敗"})), \
         patch("tools.analysis.fundamentals.raw_uanalyze.fetch_raw_historical_per",
               new=AsyncMock(return_value={"error": "登入失敗"})):
        r = await fetch_stock_fundamentals("2330")
    assert r == {}


@pytest.mark.asyncio
async def test_fundamentals_empty_symbol():
    r = await fetch_stock_fundamentals("  ")
    assert r == {}


@pytest.mark.asyncio
async def test_fundamentals_partial_web_only():
    """HistoricalPer 掛掉仍回 WebStockInfo 段（best-effort 分段獨立）。"""
    web = {"ua1": {"ChineseAccount": "收盤價", "Data": 2410.0}}
    with patch("tools.analysis.fundamentals.raw_uanalyze.fetch_raw_web_stock_info",
               new=AsyncMock(return_value=web)), \
         patch("tools.analysis.fundamentals.raw_uanalyze.fetch_raw_historical_per",
               new=AsyncMock(return_value={"error": "x"})):
        r = await fetch_stock_fundamentals("2330")
    assert r["收盤價"] == 2410.0
    assert "本益比" not in r
