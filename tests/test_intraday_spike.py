"""
測試 IntradaySpikeScanner 的盤中爆量邏輯。
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch

import pytest

from analysis_bot.services.intraday_spike_scanner import (
    IntradaySpikeScanner,
    BLACKOUT_MINUTES,
    MARKET_TOTAL_MIN,
)

_TW = ZoneInfo("Asia/Taipei")


def _tw_time(hour: int, minute: int) -> datetime:
    """產生台北時間的 datetime 供測試用。"""
    return datetime(2026, 4, 7, hour, minute, 0, tzinfo=_TW)


class TestTimeProgress:
    def test_at_market_open(self):
        scanner = IntradaySpikeScanner()
        assert scanner.get_elapsed_minutes(_tw_time(9, 0)) == 0
        assert scanner.get_time_progress(_tw_time(9, 0)) == 0.0

    def test_at_half_time(self):
        scanner = IntradaySpikeScanner()
        # 09:00 + 135 分鐘 = 11:15
        elapsed = scanner.get_elapsed_minutes(_tw_time(11, 15))
        assert elapsed == 135
        progress = scanner.get_time_progress(_tw_time(11, 15))
        assert abs(progress - 135 / MARKET_TOTAL_MIN) < 0.001

    def test_at_market_close(self):
        scanner = IntradaySpikeScanner()
        elapsed = scanner.get_elapsed_minutes(_tw_time(13, 30))
        assert elapsed == 270
        progress = scanner.get_time_progress(_tw_time(13, 30))
        assert progress == 1.0

    def test_before_open(self):
        scanner = IntradaySpikeScanner()
        assert scanner.get_elapsed_minutes(_tw_time(8, 30)) == 0
        assert scanner.get_time_progress(_tw_time(8, 30)) == 0.0


class TestDynamicThreshold:
    def test_blackout_period(self):
        scanner = IntradaySpikeScanner()
        assert scanner.get_effective_threshold(0, 1.5) == float("inf")
        assert scanner.get_effective_threshold(29, 1.5) == float("inf")

    def test_early_session(self):
        scanner = IntradaySpikeScanner()
        threshold = scanner.get_effective_threshold(30, 1.5)
        assert abs(threshold - 1.5 * 1.8) < 0.001  # 2.7x

    def test_mid_session(self):
        scanner = IntradaySpikeScanner()
        threshold = scanner.get_effective_threshold(90, 1.5)
        assert abs(threshold - 1.5 * 1.3) < 0.001  # 1.95x

    def test_late_session(self):
        scanner = IntradaySpikeScanner()
        threshold = scanner.get_effective_threshold(120, 1.5)
        assert threshold == 1.5  # 標準閾值

    def test_custom_base_ratio(self):
        scanner = IntradaySpikeScanner()
        threshold = scanner.get_effective_threshold(150, 2.0)
        assert threshold == 2.0


class TestScanIntraday:
    """測試 scan_intraday 的爆量邏輯（mock fetch_intraday_data）。"""

    @pytest.mark.asyncio
    async def test_blackout_period_returns_empty(self):
        scanner = IntradaySpikeScanner()
        ma20 = {"2330": {"name": "台積電", "market": "TWSE", "ma20_lots": 1000.0}}

        results = await scanner.scan_intraday(
            ma20_snapshot=ma20,
            now_tw=_tw_time(9, 10),  # 開盤後 10 分鐘（黑名單期）
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_spike_detected_fallback_ma20(self):
        """vol_19d_sum_lots 不存在時，fallback 用 ma20_lots，ratio = current / ma20。"""
        scanner = IntradaySpikeScanner()
        ma20 = {"2330": {"name": "台積電", "market": "TWSE", "ma20_lots": 500.0}}

        # 11:15（135 分鐘，超過 120 min），閾值 = base_ratio = 1.0
        # ratio = 1200 / 500 = 2.4x > 1.0 → 偵測到
        with patch.object(scanner, "fetch_intraday_data", return_value={
            "2330": {"lots": 1200, "close": 800.0, "change_pct": 1.5}
        }):
            results = await scanner.scan_intraday(
                ma20_snapshot=ma20,
                base_spike_ratio=1.0,
                min_lots=100,
                now_tw=_tw_time(11, 15),
            )
        assert len(results) == 1
        assert results[0].ticker == "2330"
        assert abs(results[0].spike_ratio - 2.4) < 0.01
        assert results[0].close == 800.0
        assert results[0].change_pct == 1.5

    @pytest.mark.asyncio
    async def test_spike_detected_vol19d_formula(self):
        """vol_19d_sum_lots 存在時，MA20 = (今日量 + 19日加總) / 20。"""
        scanner = IntradaySpikeScanner()
        # 過去 19 日加總 = 9500 張（平均 500 張/日）
        ma20 = {"2330": {"name": "台積電", "market": "TWSE", "ma20_lots": 500.0, "vol_19d_sum_lots": 9500.0}}

        # 今日量 2000 張 → MA20 = (2000 + 9500) / 20 = 575 → ratio = 2000 / 575 ≈ 3.48x
        with patch.object(scanner, "fetch_intraday_data", return_value={
            "2330": {"lots": 2000, "close": 800.0, "change_pct": 2.0}
        }):
            results = await scanner.scan_intraday(
                ma20_snapshot=ma20,
                base_spike_ratio=1.5,
                min_lots=100,
                now_tw=_tw_time(11, 15),
            )
        assert len(results) == 1
        expected_ma20 = (2000 + 9500) / 20
        expected_ratio = 2000 / expected_ma20
        assert abs(results[0].spike_ratio - expected_ratio) < 0.01

    @pytest.mark.asyncio
    async def test_below_threshold_not_included(self):
        scanner = IntradaySpikeScanner()
        ma20 = {"2330": {"name": "台積電", "market": "TWSE", "ma20_lots": 1000.0}}

        # ratio = 100 / 1000 = 0.1x → 遠低於閾值 1.5x
        with patch.object(scanner, "fetch_intraday_data", return_value={
            "2330": {"lots": 100, "close": 800.0, "change_pct": 0.5}
        }):
            results = await scanner.scan_intraday(
                ma20_snapshot=ma20,
                now_tw=_tw_time(12, 0),
            )
        assert results == []

    @pytest.mark.asyncio
    async def test_min_lots_filter(self):
        scanner = IntradaySpikeScanner()
        ma20 = {"2330": {"name": "台積電", "market": "TWSE", "ma20_lots": 100.0}}

        # 成交量 50 張（低於 min_lots=200）
        with patch.object(scanner, "fetch_intraday_data", return_value={
            "2330": {"lots": 50, "close": 800.0, "change_pct": None}
        }):
            results = await scanner.scan_intraday(
                ma20_snapshot=ma20,
                min_lots=200,
                now_tw=_tw_time(12, 0),
            )
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_snapshot_returns_empty(self):
        scanner = IntradaySpikeScanner()
        results = await scanner.scan_intraday(
            ma20_snapshot={},
            now_tw=_tw_time(11, 0),
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_sort_by_change(self):
        from analysis_bot.services.volume_spike_scanner import SpikeSortBy

        scanner = IntradaySpikeScanner()
        ma20 = {
            "2330": {"name": "台積電", "market": "TWSE", "ma20_lots": 100.0},
            "2454": {"name": "聯發科", "market": "TWSE", "ma20_lots": 100.0},
        }

        with patch.object(scanner, "fetch_intraday_data", return_value={
            "2330": {"lots": 500, "close": 800.0, "change_pct": 1.0},
            "2454": {"lots": 500, "close": 1800.0, "change_pct": 5.0},
        }):
            results = await scanner.scan_intraday(
                ma20_snapshot=ma20,
                base_spike_ratio=1.0,
                min_lots=100,
                sort_by=SpikeSortBy.CHANGE,
                now_tw=_tw_time(11, 0),
            )

        assert len(results) == 2
        assert results[0].ticker == "2454"  # 漲幅 5.0%
        assert results[1].ticker == "2330"  # 漲幅 1.0%

    @pytest.mark.asyncio
    async def test_sort_by_change_tiebreak_by_ratio(self):
        """漲幅相同時，按爆量倍數降序。"""
        from analysis_bot.services.volume_spike_scanner import SpikeSortBy

        scanner = IntradaySpikeScanner()
        ma20 = {
            "2330": {"name": "台積電", "market": "TWSE", "ma20_lots": 100.0},
            "2454": {"name": "聯發科", "market": "TWSE", "ma20_lots": 50.0},
        }

        # 同漲幅 3.0%，2330: ratio=300/100=3x，2454: ratio=300/50=6x → 2454 先
        with patch.object(scanner, "fetch_intraday_data", return_value={
            "2330": {"lots": 300, "close": 800.0, "change_pct": 3.0},
            "2454": {"lots": 300, "close": 1800.0, "change_pct": 3.0},
        }):
            results = await scanner.scan_intraday(
                ma20_snapshot=ma20,
                base_spike_ratio=1.0,
                min_lots=100,
                sort_by=SpikeSortBy.CHANGE,
                now_tw=_tw_time(11, 0),
            )

        assert len(results) == 2
        assert results[0].ticker == "2454"  # 同漲幅，倍數 6x 優先
        assert results[1].ticker == "2330"  # 倍數 3x


class TestParsePrice:
    def test_valid_price(self):
        from analysis_bot.services.intraday_spike_scanner import _parse_price
        assert _parse_price("1955.0000") == 1955.0
        assert _parse_price("200.5000") == 200.5

    def test_dash_returns_none(self):
        from analysis_bot.services.intraday_spike_scanner import _parse_price
        assert _parse_price("-") is None
        assert _parse_price("--") is None
        assert _parse_price("---") is None

    def test_empty_returns_none(self):
        from analysis_bot.services.intraday_spike_scanner import _parse_price
        assert _parse_price(None) is None
        assert _parse_price("") is None

    def test_zero_returns_none(self):
        from analysis_bot.services.intraday_spike_scanner import _parse_price
        assert _parse_price("0") is None
        assert _parse_price("0.0000") is None

    def test_comma_separated(self):
        from analysis_bot.services.intraday_spike_scanner import _parse_price
        assert _parse_price("1,955.00") == 1955.0
