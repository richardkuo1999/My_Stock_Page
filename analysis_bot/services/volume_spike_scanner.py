"""
VolumeSpikeScanner — Detects stocks with abnormal volume spikes.
台灣上市櫃股票爆量偵測：每日掃描，找出成交量異常放大的個股。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from urllib.parse import quote
from zoneinfo import ZoneInfo

import feedparser
import pandas as pd
import yfinance as yf

from .market_data_fetcher import MarketDataFetcher

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_MIN_VOLUME_LOTS = 100  # 預過濾：API 資料 ≥ 100 張（排除極度冷門股，加速 yfinance 下載）
DEFAULT_SPIKE_RATIO = 1.5
DEFAULT_MA_DAYS = 20
# 若日線最後一根早於「今天（台北）」超過此曆日天數，視為過期資料略過（長假可調大）
MAX_BAR_AGE_CALENDAR_DAYS = 7
# 爆量後題材／新聞＋AI：預設只處理前 N 檔（試跑可設 1）
DEFAULT_NEWS_ENRICH_TOP_N = 1

_TW = ZoneInfo("Asia/Taipei")


class SpikeSortBy(Enum):
    """爆量結果排序方式"""
    RATIO = "ratio"      # 按爆量倍數降序（預設，向後兼容）
    CHANGE = "change"    # 按漲幅降序

    @property
    def display_name(self) -> str:
        """取得用於顯示的中文名稱"""
        return {"ratio": "爆量倍數", "change": "漲幅"}[self.value]


@dataclass
class VolumeSpikeResult:
    """Single stock's volume spike result."""

    ticker: str
    name: str
    close: float
    today_volume: int  # in shares
    ma20_volume: float  # in shares（最近 ma_days 日算術平均，含當日）
    spike_ratio: float
    market: str  # "TWSE" or "TPEx"
    change_pct: float | None = None  # 當日漲跌幅 %
    trade_date: date | None = None  # Yahoo 日線最後一根日期（yfinance）
    yahoo_bar_is_taipei_today: bool = False  # 最後一根日線是否等於台北曆日「今天」
    news_titles: list[str] = field(default_factory=list)
    analysis: str = ""


@dataclass
class VolumeSpikeScan:
    """一次掃描結果與人類可讀的資料日期說明（供標題列印）。"""

    results: list[VolumeSpikeResult]
    data_date_caption: str
    # 全市場 MA20 快照（ticker -> {ma20_lots, name, market}），供盤中偵測使用
    ma20_snapshot: dict[str, dict] = field(default_factory=dict)


def _today_tw() -> date:
    return datetime.now(_TW).date()


def is_yahoo_daily_bar_taipei_today(bar_date: date | None) -> bool:
    """
    最後一根日線的「日期」是否等於台北曆日「今天」。
    僅能判斷曆日對齊；無法分辨該日是否為台股交易日（休市日／長假另當別論）。
    盤中或未更新時常為 False（最後一根仍為前一交易日）。
    """
    if bar_date is None:
        return False
    return bar_date == _today_tw()


def _is_stale_bar(bar_date: date | None, max_days: int = MAX_BAR_AGE_CALENDAR_DAYS) -> bool:
    """最後日線若過舊（長假後尚未更新等），略過該檔。"""
    if bar_date is None:
        return True
    return (_today_tw() - bar_date).days > max_days


def _extract_ohlcv(
    hist: pd.DataFrame,
    yf_t: str,
    yf_tickers: list[str],
) -> pd.DataFrame | None:
    """從 yfinance 批次下載結果取出單一 ticker 的 OHLCV。"""
    if hist is None or len(hist) == 0:
        return None
    if len(yf_tickers) == 1:
        if "Volume" in hist.columns:
            return hist
        try:
            return hist[yf_tickers[0]]
        except (KeyError, TypeError):
            return None
    try:
        return hist[yf_t]
    except (KeyError, TypeError):
        return None


def _metrics_from_daily_frame(
    hist_df: pd.DataFrame,
    ma_days: int,
    min_volume_shares: int,
) -> dict | None:
    """
    以單一來源日線（Volume／Close）計算：最後一根成交量、最近 ma_days 日均量（**含當日**）、倍數、收盤、漲跌幅、K 線日期。
    均量定義與多數看盤「成交量 SMA20」一致。
    """
    if hist_df is None:
        return None
    if "Volume" not in hist_df.columns or "Close" not in hist_df.columns:
        return None
    vol = hist_df["Volume"].dropna().astype(float)
    close = hist_df["Close"].dropna().astype(float)
    if len(vol) < ma_days or len(close) < 2:
        return None
    last_vol = float(vol.iloc[-1])
    if last_vol < float(min_volume_shares):
        return None
    ma_window = vol.iloc[-ma_days:]
    ma_vol = float(ma_window.mean())
    if ma_vol <= 0:
        return None
    ratio = last_vol / ma_vol
    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    chg = ((last_close - prev_close) / prev_close * 100) if prev_close else None
    ts = vol.index[-1]
    tsn = pd.Timestamp(ts)
    if tsn.tzinfo is not None:
        bar_date = tsn.tz_convert(_TW).date()
    else:
        bar_date = tsn.date()
    return {
        "volume": int(round(last_vol)),
        "ma_vol": ma_vol,
        "ratio": ratio,
        "close": last_close,
        "change_pct": chg,
        "bar_date": bar_date,
        "bar_is_calendar_today": is_yahoo_daily_bar_taipei_today(bar_date),
    }


def _build_data_date_caption(stocks: list[dict]) -> str:
    """依上市／櫃買 API 的 trade_date 彙總說明（兩所更新節奏可能差一日）。"""
    tw = {s["trade_date"] for s in stocks if s.get("market") == "TWSE" and s.get("trade_date")}
    tp = {s["trade_date"] for s in stocks if s.get("market") == "TPEx" and s.get("trade_date")}
    if not tw and not tp:
        return "資料日未知（API 未含有效 Date）"
    if len(tw) == 1 and len(tp) == 1 and tw == tp:
        d = next(iter(tw))
        return f"資料日 {d.isoformat()}（上市／櫃買一致）"
    parts: list[str] = []
    if tw:
        if len(tw) == 1:
            parts.append(f"上市 {next(iter(tw)).isoformat()}")
        else:
            parts.append(f"上市 多個日期 {sorted(tw)}")
    if tp:
        if len(tp) == 1:
            parts.append(f"櫃買 {next(iter(tp)).isoformat()}")
        else:
            parts.append(f"櫃買 多個日期 {sorted(tp)}")
    return "、".join(parts)


def sort_results(results: list[VolumeSpikeResult], sort_by: SpikeSortBy) -> list[VolumeSpikeResult]:
    """根據指定方式排序爆量結果並回傳新列表。

    Args:
        results: 爆量結果列表
        sort_by: 排序方式枚舉

    Returns:
        排序後的新列表
    """
    if sort_by == SpikeSortBy.RATIO:
        # 按倍數降序（原邏輯）
        return sorted(results, key=lambda r: r.spike_ratio, reverse=True)
    elif sort_by == SpikeSortBy.CHANGE:
        # 按漲幅降序，同漲幅再按倍數降序；None 值排最後
        return sorted(
            results,
            key=lambda r: (r.change_pct is not None, r.change_pct if r.change_pct is not None else float('-inf'), r.spike_ratio),
            reverse=True
        )
    return results


def _build_spike_scan_caption(
    results: list[VolumeSpikeResult],
    all_stocks: list[dict],
) -> str:
    """標題說明：Yahoo Finance（yfinance）日線結算日（與表格數字同源）。"""
    label = "Yahoo 日線"
    tw = _today_tw()
    if results:
        dates = sorted({r.trade_date for r in results if r.trade_date})
        today_note = ""
        if all(r.yahoo_bar_is_taipei_today for r in results):
            today_note = f"｜最後一根日線＝台北曆日今日（{tw.isoformat()}）"
        elif any(r.yahoo_bar_is_taipei_today for r in results):
            today_note = "｜部分標的最後一根非今日曆日（盤中／Yahoo 延遲時常見）"
        else:
            today_note = (
                f"｜最後一根多為前一交易日（今日曆日 {tw.isoformat()}；盤中或收盤後尚未更新屬正常）"
            )
        if len(dates) == 1:
            extra = "；與證交所網頁顯示可能有修正時間差"
            return f"{label}結算日 {dates[0].isoformat()}（量／價／倍數同源{extra}）{today_note}"
        return f"{label}結算日：{'、'.join(d.isoformat() for d in dates)}{today_note}"
    ref = _build_data_date_caption(all_stocks)
    return f"無符合標的。證交所／櫃買列表參考：{ref}"


class VolumeSpikeScanner:
    """Scans the full TW market for volume spikes."""

    async def scan(
        self,
        min_volume_lots: int = DEFAULT_MIN_VOLUME_LOTS,
        spike_ratio: float = DEFAULT_SPIKE_RATIO,
        ma_days: int = DEFAULT_MA_DAYS,
        sort_by: SpikeSortBy = SpikeSortBy.RATIO,
    ) -> VolumeSpikeScan:
        """
        Main scan: fetch today's market → filter → yfinance 日線 OHLCV → compute spike ratio.
        倍數 = 當日量 ÷ 最近 ma_days 日均量（**含當日**，與常見 SMA 一致）。
        日線僅使用 Yahoo Finance（yfinance），不呼叫富果 API。

        Args:
            min_volume_lots: 預過濾最小成交量（張）
            spike_ratio: 爆量倍數閾值（≥ 此值才列入結果）
            ma_days: 均量窗口（日）
            sort_by: 排序方式（預設按倍數降序，保持向後兼容）

        Returns:
            VolumeSpikeScan: 掃描結果與資料日期說明
        """
        # 1. Fetch all market daily data
        all_stocks = await MarketDataFetcher.fetch_all_market_daily()
        if not all_stocks:
            logger.warning("No market data fetched. Is the market open today?")
            return VolumeSpikeScan([], _build_spike_scan_caption([], []))

        # 2. Filter by minimum volume
        min_shares = min_volume_lots * 1000
        filtered = [s for s in all_stocks if s["volume_shares"] >= min_shares]
        logger.info(
            "Volume filter: %d/%d stocks have >= %d lots",
            len(filtered),
            len(all_stocks),
            min_volume_lots,
        )

        if not filtered:
            return VolumeSpikeScan([], _build_spike_scan_caption([], all_stocks))

        # 3. yfinance ticker（.TW / .TWO）
        stock_map: dict[str, dict] = {}
        yf_tickers: list[str] = []
        for s in filtered:
            suffix = ".TW" if s["market"] == "TWSE" else ".TWO"
            yf_t = f"{s['ticker']}{suffix}"
            yf_tickers.append(yf_t)
            stock_map[yf_t] = s

        results: list[VolumeSpikeResult] = []
        ma20_snapshot: dict[str, dict] = {}

        def _try_append(yf_t: str, m: dict | None) -> None:
            if m is None:
                return
            if _is_stale_bar(m["bar_date"]):
                logger.debug("Skip stale bar %s date=%s", yf_t, m["bar_date"])
                return
            s = stock_map[yf_t]
            # 無論是否爆量，都記錄 MA20 快照（供盤中偵測使用，單位：張）
            ma20_snapshot[s["ticker"]] = {
                "name": s["name"],
                "market": s["market"],
                "ma20_lots": round(m["ma_vol"] / 1000, 4),
            }
            if m["ratio"] < spike_ratio:
                return
            results.append(
                VolumeSpikeResult(
                    ticker=s["ticker"],
                    name=s["name"],
                    close=m["close"],
                    today_volume=m["volume"],
                    ma20_volume=m["ma_vol"],
                    spike_ratio=m["ratio"],
                    market=s["market"],
                    change_pct=m["change_pct"],
                    trade_date=m["bar_date"],
                    yahoo_bar_is_taipei_today=m.get(
                        "bar_is_calendar_today",
                        is_yahoo_daily_bar_taipei_today(m.get("bar_date")),
                    ),
                )
            )

        logger.info("Batch downloading %d tickers from yfinance...", len(yf_tickers))

        # 分批下載避免 DNS/連線問題（每批 100 檔，threads=False）
        BATCH_SIZE = 100

        def _download_batch(tickers: list[str]) -> pd.DataFrame:
            return yf.download(
                tickers,
                period="3mo",
                group_by="ticker",
                threads=False,  # 關閉多執行緒避免 DNS 耗盡
                progress=False,
            )

        results: list[VolumeSpikeResult] = []
        for i in range(0, len(yf_tickers), BATCH_SIZE):
            batch = yf_tickers[i : i + BATCH_SIZE]
            logger.info("Downloading batch %d-%d/%d...", i + 1, min(i + BATCH_SIZE, len(yf_tickers)), len(yf_tickers))
            try:
                hist = await asyncio.to_thread(_download_batch, batch)
            except Exception as e:
                logger.warning("Batch %d-%d download failed: %s", i + 1, len(batch), e)
                continue

            # 處理這批下載結果
            for yf_t in batch:
                try:
                    ohlcv = _extract_ohlcv(hist, yf_t, batch)
                    m = _metrics_from_daily_frame(ohlcv, ma_days, min_shares)
                    _try_append(yf_t, m)
                except Exception as e:
                    logger.debug("Skip %s: %s", yf_t, e)

        results = sort_results(results, sort_by)
        n_bar_today = sum(1 for r in results if r.yahoo_bar_is_taipei_today)
        logger.info(
            "爆量結果：%d 檔（倍數≥%.1fx、最少 %d 張、MA%d 含當日）；最後一根日線＝今日曆日：%d 檔",
            len(results),
            spike_ratio,
            min_volume_lots,
            ma_days,
            n_bar_today,
        )
        caption = _build_spike_scan_caption(results, all_stocks)
        logger.info("MA20 snapshot collected: %d stocks", len(ma20_snapshot))
        return VolumeSpikeScan(results, caption, ma20_snapshot)

    async def enrich_with_news(
        self,
        results: list[VolumeSpikeResult],
        top_n: int = DEFAULT_NEWS_ENRICH_TOP_N,
        max_news_per_stock: int = 5,
    ) -> list[VolumeSpikeResult]:
        """前 top_n 檔（依爆量排序後）：Google News 標題 + AI 簡析。預設 1 檔試跑。"""
        from .ai_service import AIService

        ai = AIService()
        to_enrich = results[:top_n]
        if not to_enrich:
            return results

        tasks = [self._fetch_google_news(r.ticker, r.name, max_news_per_stock) for r in to_enrich]
        news_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, r in enumerate(to_enrich):
            if isinstance(news_results[i], Exception):
                logger.warning("News fetch failed for %s: %s", r.ticker, news_results[i])
                continue
            r.news_titles = news_results[i]

        for r in to_enrich:
            if not r.news_titles:
                r.analysis = "近期無相關新聞"
                continue
            try:
                r.analysis = await self._ai_analyze(ai, r)
            except Exception as e:
                logger.warning("AI analysis failed for %s: %s", r.ticker, e)
                r.analysis = "AI 分析暫時無法使用"

        return results

    @staticmethod
    async def _fetch_google_news(
        ticker: str,
        name: str,
        limit: int = 5,
    ) -> list[str]:
        query = quote(f"{name} {ticker} 股票")
        url = (
            f"https://news.google.com/rss/search?q={query}+when:60d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        )
        feed = await asyncio.to_thread(feedparser.parse, url)
        titles = []
        for entry in feed.entries[:limit]:
            title = entry.get("title", "").strip()
            if title:
                titles.append(title)
        return titles

    @staticmethod
    async def _ai_analyze(ai, result: VolumeSpikeResult) -> str:
        from .ai_service import RequestType

        news_block = "\n".join(f"- {t}" for t in result.news_titles)
        td = result.trade_date.isoformat() if result.trade_date else "未知"
        src = "Yahoo Finance（yfinance）"
        prompt = (
            f"你是一位專業的台股分析師。以下是一檔爆量的股票資訊（{src} 日線，結算日 {td}）：\n\n"
            f"股票：{result.name}（{result.ticker}）\n"
            f"市場：{result.market}\n"
            f"收盤價：{result.close}\n"
            f"成交量：{result.today_volume // 1000:,} 張\n"
            f"20日均量（含當日，{src}）：{result.ma20_volume / 1000:,.0f} 張\n"
            f"爆量倍數：{result.spike_ratio:.1f}x\n\n"
            f"近 60 天相關新聞標題：\n{news_block}\n\n"
            f"請用繁體中文，以 2-3 句話簡要分析這檔股票爆量的可能原因。"
            f"涵蓋：題材面（產業趨勢）、消息面（法人動向、財報、政策）、"
            f"護城河（競爭優勢）。若資訊不足請直接說明。"
        )
        return await ai.call(RequestType.TEXT, contents=prompt)
