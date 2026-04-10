"""
IntradaySpikeScanner — 盤中全市場爆量偵測

資料來源：TWSE mis.twse.com.tw（非官方，免費，批量查詢）
MA20 基準：前一個交易日收盤後存入 IntradayMA20Snapshot 表，盤中直接讀取

爆量判斷：
    time_progress  = elapsed_minutes / 270.0   （09:00~13:30 共 270 分鐘）
    projected_vol  = current_vol_lots / time_progress
    spike_ratio    = projected_vol / ma20_lots
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from datetime import datetime, time
from zoneinfo import ZoneInfo

import aiohttp

from .volume_spike_scanner import (
    VolumeSpikeResult,
    SpikeSortBy,
    sort_results,
    _today_tw,
)

logger = logging.getLogger(__name__)

_TW = ZoneInfo("Asia/Taipei")

# --- 常數 ---
MIS_BASE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"


def _parse_price(raw: str | None) -> float | None:
    """解析 MIS API 價格字串；"-" / 空值 / 0 皆回傳 None。"""
    if not raw or raw.strip() in ("-", "--", "---"):
        return None
    try:
        v = float(raw.replace(",", ""))
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


MIS_BATCH_SIZE = 100          # 每批最多 100 支（URL 安全長度上限）
MIS_CONCURRENT = 10           # 最大並發批次數
MIS_TIMEOUT = aiohttp.ClientTimeout(total=10)

MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(13, 30)
MARKET_TOTAL_MIN = 270        # 09:00~13:30

# 開盤後前 30 分鐘不推播（競價後波動大）
BLACKOUT_MINUTES = 30

_MIS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StockBot/1.0)",
    "Referer": "https://mis.twse.com.tw",
}
_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def _mis_ex_ch(ticker: str, market: str) -> str:
    """產生 mis API 的 ex_ch 代碼：上市用 tse_XXXX.tw，上櫃用 otc_XXXX.tw。"""
    prefix = "tse" if market == "TWSE" else "otc"
    return f"{prefix}_{ticker}.tw"


class IntradaySpikeScanner:
    """盤中全市場爆量掃描器。"""

    def get_elapsed_minutes(self, now_tw: datetime | None = None) -> int:
        """計算目前台北時間距開盤（09:00）的分鐘數。"""
        now = now_tw or datetime.now(_TW)
        open_dt = now.replace(hour=9, minute=0, second=0, microsecond=0)
        delta = (now - open_dt).total_seconds() / 60
        return max(int(delta), 0)

    def get_time_progress(self, now_tw: datetime | None = None) -> float:
        """計算目前交易時段進度（0.0~1.0）。"""
        elapsed = self.get_elapsed_minutes(now_tw)
        return min(elapsed / MARKET_TOTAL_MIN, 1.0)

    def get_effective_threshold(self, elapsed_min: int, base_ratio: float) -> float:
        """依開盤時間動態調整爆量閾值，降低開盤前段的誤判率。"""
        if elapsed_min < BLACKOUT_MINUTES:
            return float("inf")  # 黑名單期，不通知
        elif elapsed_min < 60:
            return base_ratio * 1.8  # 30~60 分鐘：需 2.7x
        elif elapsed_min < 120:
            return base_ratio * 1.3  # 60~120 分鐘：需 1.95x
        return base_ratio             # 120+ 分鐘：標準閾值

    async def fetch_intraday_data(
        self,
        symbols: list[tuple[str, str]],
    ) -> dict[str, dict]:
        """
        批量從 TWSE mis API 取得盤中資料。

        Args:
            symbols: list of (ticker, market)，market 為 "TWSE" 或 "TPEx"

        Returns:
            dict[ticker, {"lots": int, "close": float, "change_pct": float | None}]
        """
        result: dict[str, dict] = {}

        async def _fetch_batch(
            session: aiohttp.ClientSession,
            batch: list[tuple[str, str]],
        ) -> None:
            ex_ch = "|".join(_mis_ex_ch(t, m) for t, m in batch)
            params = {"ex_ch": ex_ch, "json": "1", "delay": "0"}
            try:
                async with session.get(
                    MIS_BASE_URL,
                    params=params,
                    headers=_MIS_HEADERS,
                    ssl=_SSL_CONTEXT,
                    timeout=MIS_TIMEOUT,
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                    for item in data.get("msgArray", []):
                        ticker = item.get("c", "")
                        if not ticker:
                            continue
                        vol_str = item.get("v", "0") or "0"  # 累積成交量（張）

                        try:
                            lots = int(float(vol_str))
                        except (ValueError, TypeError):
                            lots = 0

                        # 昨收（計算漲跌幅基準）
                        prev = _parse_price(item.get("y")) or 0.0

                        # 現價 fallback 鏈：最新成交 z → 昨收 y → 開盤 o → (最高+最低)/2
                        _h = _parse_price(item.get("h")) or 0
                        _l = _parse_price(item.get("l")) or 0
                        close = (
                            _parse_price(item.get("z"))
                            or _parse_price(item.get("y"))
                            or _parse_price(item.get("o"))
                            or ((_h + _l) / 2 if _h or _l else None)
                        )

                        change_pct = ((close - prev) / prev * 100) if close and prev else None

                        result[ticker] = {
                            "lots": lots,
                            "close": close or 0.0,
                            "change_pct": change_pct,
                        }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("mis API batch failed (%d stocks): %s", len(batch), e)

        batches = [
            symbols[i : i + MIS_BATCH_SIZE]
            for i in range(0, len(symbols), MIS_BATCH_SIZE)
        ]

        connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
        async with aiohttp.ClientSession(connector=connector) as session:
            sem = asyncio.Semaphore(MIS_CONCURRENT)

            async def _limited(batch):
                async with sem:
                    await _fetch_batch(session, batch)

            await asyncio.gather(*(_limited(b) for b in batches))

        return result

    async def scan_intraday(
        self,
        ma20_snapshot: dict[str, dict],
        base_spike_ratio: float = 1.5,
        min_lots: int = 200,
        sort_by: SpikeSortBy = SpikeSortBy.RATIO,
        now_tw: datetime | None = None,
    ) -> list[VolumeSpikeResult]:
        """
        盤中全市場爆量掃描主流程。

        Args:
            ma20_snapshot: {ticker: {"ma20_lots", "name", "market"}}（前日快取）
            base_spike_ratio: 基礎閾值（依時段動態調整）
            min_lots: 盤中最低成交量門檻（張）
            sort_by: 排序方式
            now_tw: 供測試用的當前時間（None 表示使用系統時間）

        Returns:
            符合盤中爆量條件的 VolumeSpikeResult 列表
        """
        elapsed = self.get_elapsed_minutes(now_tw)
        time_progress = self.get_time_progress(now_tw)
        threshold = self.get_effective_threshold(elapsed, base_spike_ratio)

        if threshold == float("inf"):
            logger.info("盤中爆量：開盤黑名單期（elapsed=%d min），跳過", elapsed)
            return []

        if time_progress <= 0:
            logger.info("盤中爆量：交易尚未開始，跳過")
            return []

        logger.info(
            "盤中爆量掃描：elapsed=%d min，progress=%.1f%%，threshold=%.2fx，stocks=%d",
            elapsed,
            time_progress * 100,
            threshold,
            len(ma20_snapshot),
        )

        # 取得盤中成交量與現價
        symbols = [(t, v["market"]) for t, v in ma20_snapshot.items()]
        intraday_data = await self.fetch_intraday_data(symbols)

        today = _today_tw()
        results: list[VolumeSpikeResult] = []

        for ticker, snap in ma20_snapshot.items():
            row = intraday_data.get(ticker)
            if row is None:
                continue
            current_lots = row["lots"]
            if current_lots <= 0 or current_lots < min_lots:
                continue

            # MA20 計算：優先使用盤前 vol_19d_sum，fallback 舊版 ma20_lots
            vol_19d_sum = snap.get("vol_19d_sum_lots")
            if vol_19d_sum and vol_19d_sum > 0:
                # 新版：(今日即時量 + 過去 19 日加總) / 20
                ma20_lots = (current_lots + vol_19d_sum) / 20
            else:
                # 舊版 fallback（收盤掃描存的均量）
                ma20_lots = snap.get("ma20_lots", 0.0)

            if ma20_lots <= 0:
                continue

            ratio = current_lots / ma20_lots

            if ratio < threshold:
                continue

            results.append(
                VolumeSpikeResult(
                    ticker=ticker,
                    name=snap["name"],
                    close=row["close"],
                    today_volume=int(current_lots * 1000),   # 今日即時量（股）
                    ma20_volume=ma20_lots * 1000,             # MA20（股）
                    spike_ratio=ratio,
                    market=snap["market"],
                    change_pct=row["change_pct"],
                    trade_date=today,
                    yahoo_bar_is_taipei_today=True,
                )
            )

        return sort_results(results, sort_by)
