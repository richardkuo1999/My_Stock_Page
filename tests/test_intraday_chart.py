"""Tests for tools/draw_intraday_chart.py"""

import os
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from tools.draw_intraday_chart import (
    _parse_candles,
    _render_chart,
    draw,
)


def _sample_candles(n: int = 120) -> list[dict]:
    """Fugle intraday/candles-shaped rows: per-minute OHLCV with ISO timestamps."""
    base = pd.Timestamp("2026-08-28T09:00:00+08:00")
    rows = []
    price = 100.0
    for i in range(n):
        price += (i % 5 - 2) * 0.3
        ts = (base + pd.Timedelta(minutes=i)).isoformat()
        rows.append(
            {
                "date": ts,
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": 1000 + i,
                "average": price,
            }
        )
    return rows


def test_parse_candles_builds_indexed_frame():
    """_parse_candles turns Fugle rows into a time-indexed Close series frame."""
    df = _parse_candles(_sample_candles(10))
    assert not df.empty
    assert "Close" in df.columns
    assert isinstance(df.index, pd.DatetimeIndex)
    assert len(df) == 10


def test_parse_candles_empty():
    """_parse_candles returns an empty frame for empty input."""
    df = _parse_candles([])
    assert df.empty


def test_render_chart_generates_file():
    """_render_chart writes a PNG file to disk."""
    df = _parse_candles(_sample_candles())
    path = _render_chart(df, "2330", "台積電", prev_close=99.0)
    assert os.path.exists(path)
    assert path.endswith(".png")
    assert os.path.getsize(path) > 0
    os.unlink(path)


def test_render_chart_without_prev_close():
    """_render_chart works when prev_close is None (baseline = first price)."""
    df = _parse_candles(_sample_candles())
    path = _render_chart(df, "2330", "", prev_close=None)
    assert os.path.exists(path)
    os.unlink(path)


def test_render_chart_insufficient_data():
    """_render_chart raises ValueError with too few points."""
    df = _parse_candles(_sample_candles(1))
    with pytest.raises(ValueError, match="資料不足"):
        _render_chart(df, "2330", "", prev_close=None)


@pytest.mark.asyncio
async def test_draw_success():
    """draw() returns image_path when candles are available."""
    candles = _sample_candles()
    with patch(
        "tools.draw_intraday_chart._fetch_intraday",
        new_callable=AsyncMock,
        return_value=(candles, 99.0, "台積電"),
    ):
        result = await draw("2330")
    assert "image_path" in result
    assert os.path.exists(result["image_path"])
    os.unlink(result["image_path"])


@pytest.mark.asyncio
async def test_draw_no_data():
    """draw() returns error when no candles."""
    with patch(
        "tools.draw_intraday_chart._fetch_intraday",
        new_callable=AsyncMock,
        return_value=([], None, ""),
    ):
        result = await draw("9999")
    assert "error" in result


@pytest.mark.asyncio
async def test_draw_empty_symbol():
    """draw() returns error for empty symbol."""
    result = await draw("")
    assert "error" in result
