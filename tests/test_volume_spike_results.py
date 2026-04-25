"""Test that VolumeSpikeScanner._try_append closure correctly populates results."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from analysis_bot.services.volume_spike_scanner import VolumeSpikeScanner


def _fake_market_data():
    """Minimal market data for one stock."""
    return [
        {
            "ticker": "2330",
            "name": "台積電",
            "market": "TWSE",
            "volume_shares": 50_000_000,
        }
    ]


def _fake_ohlcv():
    """Fake OHLCV metrics that trigger a spike (ratio > 1.5)."""
    today = datetime.now()
    return {
        "close": 900.0,
        "volume": 80_000_000,
        "ma_vol": 30_000_000,
        "ratio": 2.67,
        "change_pct": 3.5,
        "prev_volume": 25_000_000,
        "ratio_t1": 3.2,
        "bar_date": today,
        "bar_is_calendar_today": True,
    }


@pytest.mark.asyncio
async def test_try_append_populates_results():
    """Verify _try_append closure writes to the same results list returned by scan()."""
    scanner = VolumeSpikeScanner()

    with (
        patch(
            "analysis_bot.services.volume_spike_scanner.MarketDataFetcher.fetch_all_market_daily",
            new_callable=AsyncMock,
            return_value=_fake_market_data(),
        ),
        patch(
            "analysis_bot.services.volume_spike_scanner._extract_ohlcv",
            return_value=None,  # placeholder, overridden below
        ),
        patch(
            "analysis_bot.services.volume_spike_scanner._metrics_from_daily_frame",
            return_value=_fake_ohlcv(),
        ),
        patch(
            "analysis_bot.services.volume_spike_scanner._is_stale_bar",
            return_value=False,
        ),
        patch("asyncio.to_thread") as mock_to_thread,
    ):
        # Make to_thread return a fake DataFrame (content doesn't matter since
        # _extract_ohlcv and _metrics_from_daily_frame are both mocked)
        import pandas as pd

        mock_to_thread.return_value = pd.DataFrame()

        scan = await scanner.scan()

    # The critical assertion: results must not be empty
    assert len(scan.results) == 1
    assert scan.results[0].ticker == "2330"
    assert scan.results[0].spike_ratio == 2.67
