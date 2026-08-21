"""Tests for tools/draw_kchart.py"""

import json
import os
from unittest.mock import AsyncMock, patch, MagicMock

import pandas as pd
import pytest

from tools.draw_kchart import draw, _render_chart, _fetch_historical


def _sample_df(days: int = 60) -> pd.DataFrame:
    """Generate sample OHLCV dataframe."""
    import numpy as np
    dates = pd.bdate_range(end=pd.Timestamp.now(), periods=days + 90)
    np.random.seed(42)
    base = 600.0
    closes = base + np.cumsum(np.random.randn(len(dates)) * 5)
    df = pd.DataFrame({
        "Open": closes - np.random.rand(len(dates)) * 3,
        "High": closes + np.random.rand(len(dates)) * 5,
        "Low": closes - np.random.rand(len(dates)) * 5,
        "Close": closes,
        "Volume": np.random.randint(1000, 50000, len(dates)).astype(float),
    }, index=dates)
    return df


@pytest.mark.asyncio
async def test_draw_success():
    """draw() should return image_path when data available."""
    sample = _sample_df()
    with patch("tools.draw_kchart._fetch_historical", new_callable=AsyncMock, return_value=sample):
        result = await draw("2330", period=60)
    assert "image_path" in result
    assert os.path.exists(result["image_path"])
    # Cleanup
    os.unlink(result["image_path"])


@pytest.mark.asyncio
async def test_draw_no_data():
    """draw() should return error when no data."""
    with patch("tools.draw_kchart._fetch_historical", new_callable=AsyncMock, return_value=None):
        result = await draw("9999")
    assert "error" in result


@pytest.mark.asyncio
async def test_draw_empty_symbol():
    """draw() should return error for empty symbol."""
    result = await draw("")
    assert "error" in result


def test_render_chart_generates_file():
    """_render_chart should create a PNG file."""
    df = _sample_df()
    path = _render_chart(df, "2330", 60)
    assert os.path.exists(path)
    assert path.endswith(".png")
    assert os.path.getsize(path) > 0
    os.unlink(path)


def test_render_chart_insufficient_data():
    """_render_chart should raise ValueError with < 5 data points."""
    df = _sample_df().tail(3)
    with pytest.raises(ValueError, match="資料不足"):
        _render_chart(df, "2330", 60)


@pytest.mark.asyncio
async def test_draw_custom_period():
    """draw() should respect custom period."""
    sample = _sample_df(120)
    with patch("tools.draw_kchart._fetch_historical", new_callable=AsyncMock, return_value=sample) as mock_fetch:
        result = await draw("2330", period=120)
    assert "image_path" in result
    os.unlink(result["image_path"])
    # Verify period was passed
    mock_fetch.assert_called_once_with("2330", 120)
