"""Tests for tools/analysis/get_stock_price.py.

get_stock_price 已改為委派 raw 層取數（raw/fugle.fetch_quote、
raw/finmind.fetch_tick_snapshot）；本檔在 raw 邊界 mock，驗證 analysis 層
的欄位映射 / 漲跌計算 / Fugle→FinMind fallback / 基本面 best-effort 疊加。
"""

import json
import os
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.analysis.get_stock_price import (
    _fetch_finmind,
    _fetch_fugle,
    fetch_price,
)

# repo 根（本檔在 tests/ 下），跨平台動態推導，勿硬編絕對路徑。
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- Fugle tests（mock raw_fugle.fetch_quote）---


@pytest.mark.asyncio
async def test_fetch_price_fugle_success():
    """Fugle 回有效 payload → fetch_price 抽欄位、source=fugle。"""
    fugle_data = {
        "closePrice": 580.0,
        "previousClose": 575.0,
        "change": 5.0,
        "changePercent": 0.87,
        "name": "台積電",
        "tradeVolume": 25000,
    }
    with patch(
        "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
        new=AsyncMock(return_value=fugle_data),
    ):
        result = await fetch_price("2330")

    assert result["symbol"] == "2330"
    assert result["name"] == "台積電"
    assert result["price"] == 580.0
    assert result["change"] == 5.0
    assert result["change_pct"] == 0.87
    assert result["volume"] == 25000
    assert result["source"] == "fugle"


@pytest.mark.asyncio
async def test_fetch_price_fugle_computes_change():
    """Fugle 有 price/previousClose 但無 change → analysis 層自算。"""
    fugle_data = {
        "lastPrice": 100.0,
        "previousClose": 95.0,
        "name": "測試",
        "tradeVolume": 1000,
    }
    with patch(
        "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
        new=AsyncMock(return_value=fugle_data),
    ):
        result = await fetch_price("9999")

    assert result["price"] == 100.0
    assert result["change"] == 5.0
    assert result["change_pct"] == pytest.approx(5.26, abs=0.01)


@pytest.mark.asyncio
async def test_fetch_price_fugle_volume_from_total():
    """回歸 B2：Fugle 把成交量放在 total.tradeVolume，頂層為空時要抽 total。"""
    fugle_data = {
        "closePrice": 580.0,
        "previousClose": 575.0,
        "change": 5.0,
        "changePercent": 0.87,
        "name": "台積電",
        "total": {"tradeVolume": 18053, "tradeValue": 43610455000},
    }
    with patch(
        "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
        new=AsyncMock(return_value=fugle_data),
    ):
        result = await fetch_price("2330")

    assert result["volume"] == 18053


@pytest.mark.asyncio
async def test_fetch_fugle_error_returns_none():
    """raw/fugle 回 {"error"} → _fetch_fugle 回 None（觸發 fallback）。"""
    with patch(
        "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
        new=AsyncMock(return_value={"error": "未設定 FUGLE_API_KEY"}),
    ):
        assert await _fetch_fugle("2330") is None


# --- FinMind fallback tests（mock raw_finmind.fetch_tick_snapshot）---


@pytest.mark.asyncio
async def test_fetch_price_finmind_fallback():
    """Fugle 不可用 → 委派 raw/finmind tick 快照成功。"""
    finmind_payload = {
        "data": [
            {
                "close": 580.0,
                "change_price": 5.0,
                "change_rate": 0.87,
                "stock_name": "台積電",
                "volume": 12000,
            }
        ]
    }
    with (
        patch(
            "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
            new=AsyncMock(return_value={"error": "no key"}),
        ),
        patch(
            "tools.analysis.get_stock_price.raw_finmind.fetch_tick_snapshot",
            return_value=finmind_payload,
        ),
    ):
        result = await fetch_price("2330")

    assert result["symbol"] == "2330"
    assert result["price"] == 580.0
    assert result["source"] == "finmind"


@pytest.mark.asyncio
async def test_fetch_finmind_error_returns_none():
    """raw/finmind 回 {"error"} → _fetch_finmind 回 None。"""
    with patch(
        "tools.analysis.get_stock_price.raw_finmind.fetch_tick_snapshot",
        return_value={"error": "額度用盡"},
    ):
        assert await _fetch_finmind("2330") is None


# --- Error cases ---


@pytest.mark.asyncio
async def test_fetch_price_not_found():
    """兩來源都失敗 → 回 error dict。"""
    with (
        patch(
            "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
            new=AsyncMock(return_value={"error": "x"}),
        ),
        patch(
            "tools.analysis.get_stock_price.raw_finmind.fetch_tick_snapshot",
            return_value={"error": "y"},
        ),
    ):
        result = await fetch_price("XXXXX")

    assert "error" in result
    assert "XXXXX" in result["error"]


@pytest.mark.asyncio
async def test_fetch_price_empty_symbol():
    """空代號 → 回 error，不發任何請求。"""
    result = await fetch_price("  ")
    assert "error" in result
    assert "請輸入股票代號" in result["error"]


# --- CLI output test ---


def _env_without_credentials() -> dict:
    """複製現有環境但清空憑證，並保留 Windows 啟動 Python 必需的變數。

    Windows 的 subprocess 需要 SystemRoot/SYSTEMROOT 才能初始化，故不清空整個
    env（那在 Windows 會讓 Python 無法啟動）。只把憑證變數設空達到「無憑證」目的。
    """
    env = dict(os.environ)
    env["FINMIND_TOKENS"] = ""
    env["FUGLE_API_KEY"] = ""
    return env


def test_cli_no_args():
    """CLI 無參數 → JSON error + exit 1。"""
    result = subprocess.run(
        [sys.executable, "-m", "tools.analysis.get_stock_price"],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=_env_without_credentials(),
        timeout=30,
    )
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert "error" in output


def test_cli_unknown_symbol():
    """CLI 無憑證查未知代號 → error + exit 1。"""
    result = subprocess.run(
        [sys.executable, "-m", "tools.analysis.get_stock_price", "ZZZZZZ"],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=_env_without_credentials(),
        timeout=30,
    )
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert "error" in output


# --- Best-effort UAnalyze fundamentals augmentation ---


def _fugle_ok():
    return {
        "closePrice": 580.0,
        "previousClose": 575.0,
        "change": 5.0,
        "changePercent": 0.87,
        "name": "台積電",
        "tradeVolume": 25000,
    }


@pytest.mark.asyncio
async def test_fetch_price_fundamentals_success():
    """價量 OK + 基本面 OK → 兩者都在 result。"""
    fake_fundamentals = {"本益比": 27.9, "最新財報": "2026年Q2"}
    with (
        patch(
            "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
            new=AsyncMock(return_value=_fugle_ok()),
        ),
        patch(
            "tools.analysis.fundamentals.fetch_stock_fundamentals",
            new=AsyncMock(return_value=fake_fundamentals),
        ),
    ):
        result = await fetch_price("2330")

    assert result["price"] == 580.0
    assert result["change"] == 5.0
    assert result["source"] == "fugle"
    assert result["fundamentals"] == fake_fundamentals


@pytest.mark.asyncio
async def test_fetch_price_fundamentals_exception_still_returns_price():
    """核心鐵則：基本面拋異常時，價量仍完整回、且無 fundamentals 鍵。"""
    with (
        patch(
            "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
            new=AsyncMock(return_value=_fugle_ok()),
        ),
        patch(
            "tools.analysis.fundamentals.fetch_stock_fundamentals",
            new=AsyncMock(side_effect=RuntimeError("UAnalyze down")),
        ),
    ):
        result = await fetch_price("2330")

    assert result["price"] == 580.0
    assert result["change"] == 5.0
    assert result["source"] == "fugle"
    assert "fundamentals" not in result
    assert "error" not in result


@pytest.mark.asyncio
async def test_fetch_price_fundamentals_timeout_still_returns_price():
    """基本面逾時時，價量仍完整回、無 fundamentals。"""
    async def _hang(_symbol):
        raise TimeoutError("simulated wait_for timeout")

    with (
        patch(
            "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
            new=AsyncMock(return_value={"lastPrice": 100.0, "previousClose": 95.0,
                                       "name": "測試", "tradeVolume": 1000}),
        ),
        patch("tools.analysis.fundamentals.fetch_stock_fundamentals",
              new=AsyncMock(side_effect=_hang)),
    ):
        result = await fetch_price("9999")

    assert result["price"] == 100.0
    assert result["change"] == 5.0
    assert "fundamentals" not in result


@pytest.mark.asyncio
async def test_fetch_price_fundamentals_empty_no_key():
    """基本面回 {} → 不加 fundamentals 鍵，價量照回。"""
    with (
        patch(
            "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
            new=AsyncMock(return_value=_fugle_ok()),
        ),
        patch("tools.analysis.fundamentals.fetch_stock_fundamentals",
              new=AsyncMock(return_value={})),
    ):
        result = await fetch_price("2330")

    assert result["price"] == 580.0
    assert "fundamentals" not in result


@pytest.mark.asyncio
async def test_fetch_price_error_does_not_call_fundamentals():
    """找不到代號時回 error，且不觸發基本面抓取。"""
    mock_fund = AsyncMock(return_value={"本益比": 1.0})
    with (
        patch(
            "tools.analysis.get_stock_price.raw_fugle.fetch_quote",
            new=AsyncMock(return_value={"error": "x"}),
        ),
        patch(
            "tools.analysis.get_stock_price.raw_finmind.fetch_tick_snapshot",
            return_value={"error": "y"},
        ),
        patch("tools.analysis.fundamentals.fetch_stock_fundamentals", new=mock_fund),
    ):
        result = await fetch_price("XXXXX")

    assert "error" in result
    assert "fundamentals" not in result
    mock_fund.assert_not_awaited()
