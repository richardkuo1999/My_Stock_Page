"""
Tests for VolumeSpikeScanner and MarketDataFetcher.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from analysis_bot.services.market_data_fetcher import MarketDataFetcher, parse_roc_minguo_date
from analysis_bot.services.spike_pager import build_spike_telegram_html_messages
from analysis_bot.services.volume_spike_formatter import (
    NAME_W,
    PRICE_CHG_W,
    RATIO_FIELD_W,
    TICKER_W,
    _fit_visual_width,
    display_width,
    format_spike_row,
    get_table_header,
    pad_stock_name,
)
from analysis_bot.services.volume_spike_scanner import (
    VolumeSpikeResult,
    _build_data_date_caption,
    _build_spike_scan_caption,
    _metrics_from_daily_frame,
    is_yahoo_daily_bar_taipei_today,
)

# --- Test data ---

MOCK_TWSE_DATA = [
    {
        "Date": "1150325",
        "Code": "2330",
        "Name": "台積電",
        "ClosingPrice": "600.00",
        "TradeVolume": "50000000",
    },
    {
        "Date": "1150325",
        "Code": "2317",
        "Name": "鴻海",
        "ClosingPrice": "100.00",
        "TradeVolume": "30000000",
    },
    {
        "Date": "1150325",
        "Code": "9999",
        "Name": "低量股",
        "ClosingPrice": "10.00",
        "TradeVolume": "500000",
    },
    {
        "Date": "1150325",
        "Code": "00878",
        "Name": "國泰永續高股息",
        "ClosingPrice": "20.00",
        "TradeVolume": "100000000",
    },
]

MOCK_TPEX_DATA = [
    {
        "Date": "1150325",
        "SecuritiesCompanyCode": "6510",
        "CompanyName": "精測",
        "Close": "500.00",
        "TradingShares": "2000000",
    },
    {
        "Date": "1150325",
        "SecuritiesCompanyCode": "ABCD",
        "CompanyName": "非數字",
        "Close": "10.00",
        "TradingShares": "1000000",
    },
]


class TestMarketDataFetcher:
    """Test TWSE/TPEx data parsing."""

    @pytest.mark.asyncio
    async def test_twse_data_parsing(self):
        """TWSE data: only 4-digit numeric codes should be included."""
        mock_session = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=MOCK_TWSE_DATA)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_resp)

        results = await MarketDataFetcher.fetch_twse_daily(session=mock_session)

        tickers = [r["ticker"] for r in results]
        assert "2330" in tickers
        assert "2317" in tickers
        assert "9999" in tickers
        assert "00878" not in tickers
        for r in results:
            assert r.get("trade_date") == date(2026, 3, 25)

    @pytest.mark.asyncio
    async def test_tpex_data_parsing(self):
        """TPEx data: only 4-digit numeric codes should be included."""
        mock_session = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=MOCK_TPEX_DATA)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_resp)

        results = await MarketDataFetcher.fetch_tpex_daily(session=mock_session)

        tickers = [r["ticker"] for r in results]
        assert "6510" in tickers
        assert "ABCD" not in tickers
        for r in results:
            assert r.get("trade_date") == date(2026, 3, 25)


def test_parse_roc_minguo_date():
    assert parse_roc_minguo_date("1150325") == date(2026, 3, 25)
    assert parse_roc_minguo_date(None) is None
    assert parse_roc_minguo_date("bad") is None


def test_build_data_date_caption_unified():
    stocks = [
        {"market": "TWSE", "trade_date": date(2026, 3, 25)},
        {"market": "TPEx", "trade_date": date(2026, 3, 25)},
    ]
    assert "2026-03-25" in _build_data_date_caption(stocks)
    assert "一致" in _build_data_date_caption(stocks)


def test_metrics_from_daily_frame_same_source():
    """量與均量皆取自同一日線；20 日均量為最近 20 根（含當日）。"""
    # 30 根：最後 20 根為 19×100 萬股 + 最後 200 萬股 → 均量 (19+2)/20*1M = 1.05M
    idx = pd.date_range("2026-01-01", periods=30, freq="B")
    vols = [1_000_000] * 29 + [2_000_000]
    closes = [100.0] * 30
    df = pd.DataFrame({"Volume": vols, "Close": closes}, index=idx)
    m = _metrics_from_daily_frame(df, ma_days=20, min_volume_shares=500_000)
    assert m is not None
    assert m["volume"] == 2_000_000
    assert m["ma_vol"] == pytest.approx(1_050_000)
    assert m["ratio"] == pytest.approx(2_000_000 / 1_050_000)


@patch("analysis_bot.services.volume_spike_scanner._today_tw")
def test_build_spike_scan_caption_with_results(mock_today):
    mock_today.return_value = date(2026, 3, 25)
    r = VolumeSpikeResult(
        ticker="2330",
        name="台積電",
        close=600.0,
        today_volume=50_000_000,
        ma20_volume=25_000_000,
        spike_ratio=2.0,
        market="TWSE",
        trade_date=date(2026, 3, 25),
        yahoo_bar_is_taipei_today=True,
    )
    cap = _build_spike_scan_caption([r], [])
    assert "2026-03-25" in cap
    assert "Yahoo" in cap
    assert "今日" in cap


@patch("analysis_bot.services.volume_spike_scanner._today_tw")
def test_is_yahoo_daily_bar_taipei_today(mock_today):
    mock_today.return_value = date(2026, 3, 25)
    assert is_yahoo_daily_bar_taipei_today(date(2026, 3, 25)) is True
    assert is_yahoo_daily_bar_taipei_today(date(2026, 3, 24)) is False
    assert is_yahoo_daily_bar_taipei_today(None) is False


class TestVolumeSpikeScanner:
    """Test spike detection logic."""

    def test_spike_ratio_calculation(self):
        """Spike ratio = today_volume / ma20_volume."""
        r = VolumeSpikeResult(
            ticker="2330",
            name="台積電",
            close=600.0,
            today_volume=50_000_000,
            ma20_volume=25_000_000,
            spike_ratio=2.0,
            market="TWSE",
        )
        assert r.spike_ratio == pytest.approx(2.0)
        assert r.today_volume / r.ma20_volume == pytest.approx(2.0)

    def test_min_volume_filter(self):
        """Stocks below 1000-lot threshold should be excluded from scan."""
        all_stocks = [
            {"ticker": "2330", "volume_shares": 50_000_000, "market": "TWSE"},
            {"ticker": "9999", "volume_shares": 500_000, "market": "TWSE"},
            {"ticker": "1234", "volume_shares": 1_000_000, "market": "TWSE"},
        ]

        min_shares = 1000 * 1000
        filtered = [s for s in all_stocks if s["volume_shares"] >= min_shares]

        assert len(filtered) == 2
        tickers = [s["ticker"] for s in filtered]
        assert "2330" in tickers
        assert "1234" in tickers
        assert "9999" not in tickers

    def test_sort_order(self):
        """Results should be sorted by spike_ratio descending (default behavior)."""
        results = [
            VolumeSpikeResult("A", "A", 10, 100, 50, 2.0, "TWSE"),
            VolumeSpikeResult("B", "B", 20, 200, 40, 5.0, "TWSE"),
            VolumeSpikeResult("C", "C", 30, 300, 200, 1.5, "TWSE"),
        ]
        results.sort(key=lambda r: r.spike_ratio, reverse=True)

        assert results[0].ticker == "B"
        assert results[1].ticker == "A"
        assert results[2].ticker == "C"

    def test_sort_by_ratio(self):
        """按倍數降序排序（預設行為）"""
        from analysis_bot.services.volume_spike_scanner import sort_results as _sort_results, SpikeSortBy

        results = [
            VolumeSpikeResult("A", "A", 10, 100, 50, 2.0, "TWSE", change_pct=5.0),
            VolumeSpikeResult("B", "B", 20, 200, 40, 5.0, "TWSE", change_pct=1.0),
            VolumeSpikeResult("C", "C", 30, 300, 200, 1.5, "TWSE", change_pct=10.0),
        ]

        results = _sort_results(results, SpikeSortBy.RATIO)

        assert results[0].ticker == "B"  # 倍數 5.0
        assert results[1].ticker == "A"  # 倍數 2.0
        assert results[2].ticker == "C"  # 倍數 1.5

    def test_sort_by_change(self):
        """按漲幅降序排序"""
        from analysis_bot.services.volume_spike_scanner import sort_results as _sort_results, SpikeSortBy

        results = [
            VolumeSpikeResult("A", "A", 10, 100, 50, 2.0, "TWSE", change_pct=5.0),
            VolumeSpikeResult("B", "B", 20, 200, 40, 5.0, "TWSE", change_pct=1.0),
            VolumeSpikeResult("C", "C", 30, 300, 200, 1.5, "TWSE", change_pct=10.0),
        ]

        results = _sort_results(results, SpikeSortBy.CHANGE)

        assert results[0].ticker == "C"  # 漲幅 10.0%
        assert results[1].ticker == "A"  # 漲幅 5.0%
        assert results[2].ticker == "B"  # 漲幅 1.0%

    def test_sort_by_change_handles_none(self):
        """按漲幅排序時，None 值應排在最後"""
        from analysis_bot.services.volume_spike_scanner import sort_results as _sort_results, SpikeSortBy

        results = [
            VolumeSpikeResult("A", "A", 10, 100, 50, 3.0, "TWSE", change_pct=None),
            VolumeSpikeResult("B", "B", 20, 200, 40, 5.0, "TWSE", change_pct=5.0),
            VolumeSpikeResult("C", "C", 30, 300, 200, 2.0, "TWSE", change_pct=None),
        ]

        results = _sort_results(results, SpikeSortBy.CHANGE)

        assert results[0].ticker == "B"  # 漲幅 5.0%
        # None 值排最後（順序可能是 A 或 C）
        assert results[1].ticker in ("A", "C")
        assert results[2].ticker in ("A", "C")

    def test_sort_by_change_with_negative(self):
        """負漲幅（下跌）應正確排序"""
        from analysis_bot.services.volume_spike_scanner import sort_results as _sort_results, SpikeSortBy

        results = [
            VolumeSpikeResult("A", "A", 10, 100, 50, 2.0, "TWSE", change_pct=5.0),
            VolumeSpikeResult("B", "B", 20, 200, 40, 5.0, "TWSE", change_pct=-3.0),
            VolumeSpikeResult("C", "C", 30, 300, 200, 1.5, "TWSE", change_pct=-10.0),
        ]

        results = _sort_results(results, SpikeSortBy.CHANGE)

        assert results[0].ticker == "A"  # +5.0%
        assert results[1].ticker == "B"  # -3.0%
        assert results[2].ticker == "C"  # -10.0%

    def test_dataclass_defaults(self):
        """VolumeSpikeResult defaults."""
        r = VolumeSpikeResult("2330", "台積電", 600, 50_000_000, 25_000_000, 2.0, "TWSE")
        assert r.news_titles == []
        assert r.analysis == ""
        assert r.yahoo_bar_is_taipei_today is False


def test_build_spike_telegram_html_messages_chunking():
    """一次全部：chunk 內筆數正確；HTML 含 <pre>。"""
    from analysis_bot.services.volume_spike_formatter import SPIKE_TABLE_CHUNK

    rows = [
        VolumeSpikeResult(
            ticker=str(i),
            name="測",
            close=10.0,
            today_volume=2_000_000,
            ma20_volume=1_000_000,
            spike_ratio=2.0,
            market="TWSE",
        )
        for i in range(25)
    ]
    msgs = build_spike_telegram_html_messages(rows, "H\n\n", chunk=10)
    assert len(msgs) == 3
    assert all("<pre>" in m and "</pre>" in m for m in msgs)
    assert sum(m.count("2.0x") for m in msgs) == 25
    msgs_one = build_spike_telegram_html_messages(rows[:5], "H\n\n", chunk=SPIKE_TABLE_CHUNK)
    assert len(msgs_one) == 1


def test_pad_stock_name_preserves_ky_suffix():
    """欄寬截斷若落在 -K 與 y 之間，不得只顯示 -K；應保留完整 -KY。"""
    name = "國泰台灣-KY"
    assert not _fit_visual_width(name, NAME_W).endswith("Y")
    assert pad_stock_name(name).rstrip().endswith("KY")


def test_spike_table_header_line_fixed_visual_width():
    """表頭列與資料列總寬一致。"""
    inner = get_table_header().removeprefix("```\n")
    first_line = inner.split("\n", 1)[0]
    expected = TICKER_W + NAME_W + PRICE_CHG_W + 1 + RATIO_FIELD_W
    assert display_width(first_line) == expected


def test_format_spike_row_fixed_visual_width():
    """Telegram 表格列顯示寬度應一致（CJK 佔 2），避免等寬字體跑版。"""
    expected = TICKER_W + NAME_W + PRICE_CHG_W + 1 + RATIO_FIELD_W
    for change_pct in (1.5, None, -9.99):
        r = VolumeSpikeResult(
            ticker="2330",
            name="台積電",
            close=600.0,
            today_volume=50_000_000,
            ma20_volume=25_000_000,
            spike_ratio=2.0,
            market="TWSE",
            change_pct=change_pct,
        )
        line = format_spike_row(r).rstrip("\n")
        assert display_width(line) == expected
