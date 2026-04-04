"""
MarketDataFetcher — Fetches daily market data from TWSE and TPEx OpenAPI.
台灣上市櫃股票每日收盤資料，無需 API Key。
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date

import ssl

import aiohttp

logger = logging.getLogger(__name__)


def parse_roc_minguo_date(raw: str | None) -> date | None:
    """
    解析證交所／櫃買 OpenAPI 的 Date 欄位（民國年 7 碼：YYYMMDD，如 1150325 = 2026-03-25）。
    若格式不符則回傳 None。
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s.isdigit():
        return None
    # 上市／櫃買全日行情皆為 7 碼：民國年(3) + 月日(4)
    if len(s) != 7:
        return None
    roc_y = int(s[:3])
    mmdd = s[3:]
    month = int(mmdd[:2])
    day = int(mmdd[2:])
    gregorian_year = roc_y + 1911
    try:
        return date(gregorian_year, month, day)
    except ValueError:
        return None


TWSE_DAILY_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAILY_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

_ORDINARY_STOCK_RE = re.compile(r"^\d{4}$")
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockBot/1.0)"}
_TIMEOUT = aiohttp.ClientTimeout(total=30)
# TWSE 憑證有問題，使用寬鬆的 SSL context
_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


class MarketDataFetcher:
    """Fetches full-market daily closing data from TWSE and TPEx."""

    @staticmethod
    async def fetch_twse_daily(session: aiohttp.ClientSession | None = None) -> list[dict]:
        """Fetch all TWSE-listed stocks' daily closing data."""
        close_after = False
        if session is None:
            connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
            session = aiohttp.ClientSession(trust_env=True, connector=connector)
            close_after = True

        try:
            async with session.get(TWSE_DAILY_URL, headers=_HEADERS, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    logger.error("TWSE API returned status %s", resp.status)
                    return []
                data = await resp.json()

            results = []
            for item in data:
                code = item.get("Code", "")
                if not _ORDINARY_STOCK_RE.match(code):
                    continue
                try:
                    trade_date = parse_roc_minguo_date(item.get("Date"))
                    vol_str = item.get("TradeVolume", "0").replace(",", "")
                    volume_shares = int(vol_str)
                    close_str = item.get("ClosingPrice", "0").replace(",", "")
                    close = float(close_str) if close_str and close_str != "--" else 0.0
                    change_str = item.get("Change", "0").replace(",", "").strip()
                    try:
                        change_val = float(change_str)
                        prev_close = close - change_val
                        change_pct = (change_val / prev_close * 100) if prev_close else 0.0
                    except (ValueError, TypeError):
                        change_pct = None
                    results.append(
                        {
                            "ticker": code,
                            "name": item.get("Name", "").strip(),
                            "close": close,
                            "volume_shares": volume_shares,
                            "market": "TWSE",
                            "change_pct": change_pct,
                            "trade_date": trade_date,
                        }
                    )
                except (ValueError, TypeError):
                    continue
            return results
        except Exception as e:
            logger.error("TWSE fetch error: %s", e)
            return []
        finally:
            if close_after:
                await session.close()

    @staticmethod
    async def fetch_tpex_daily(session: aiohttp.ClientSession | None = None) -> list[dict]:
        """Fetch all TPEx (OTC) stocks' daily closing data."""
        close_after = False
        if session is None:
            session = aiohttp.ClientSession(trust_env=True)
            close_after = True

        try:
            async with session.get(TPEX_DAILY_URL, headers=_HEADERS, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    logger.error("TPEx API returned status %s", resp.status)
                    return []
                data = await resp.json()

            results = []
            for item in data:
                code = item.get("SecuritiesCompanyCode", "")
                if not _ORDINARY_STOCK_RE.match(code):
                    continue
                try:
                    trade_date = parse_roc_minguo_date(item.get("Date"))
                    vol_str = item.get("TradingShares", "0").replace(",", "")
                    volume_shares = int(vol_str)
                    close_str = item.get("Close", "0").replace(",", "").strip()
                    close = (
                        float(close_str) if close_str and close_str not in ("--", "---") else 0.0
                    )
                    change_str = (
                        item.get("Change", "0")
                        .replace(",", "")
                        .strip()
                        .replace("+", "")
                        .replace(" ", "")
                    )
                    if change_str and change_str not in ("---", "除息", "除權", "除權息"):
                        try:
                            change_val = float(change_str)
                            prev_close = close - change_val
                            change_pct = (change_val / prev_close * 100) if prev_close else 0.0
                        except (ValueError, TypeError):
                            change_pct = None
                    else:
                        change_pct = None
                    results.append(
                        {
                            "ticker": code,
                            "name": item.get("CompanyName", "").strip(),
                            "close": close,
                            "volume_shares": volume_shares,
                            "market": "TPEx",
                            "change_pct": change_pct,
                            "trade_date": trade_date,
                        }
                    )
                except (ValueError, TypeError):
                    continue
            return results
        except Exception as e:
            logger.error("TPEx fetch error: %s", e)
            return []
        finally:
            if close_after:
                await session.close()

    @classmethod
    async def fetch_all_market_daily(
        cls, session: aiohttp.ClientSession | None = None
    ) -> list[dict]:
        """Fetch combined TWSE + TPEx daily data."""
        close_after = False
        if session is None:
            connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
            session = aiohttp.ClientSession(trust_env=True, connector=connector)
            close_after = True

        try:
            twse, tpex = await asyncio.gather(
                cls.fetch_twse_daily(session),
                cls.fetch_tpex_daily(session),
            )
            logger.info("Market data fetched: TWSE=%d, TPEx=%d", len(twse), len(tpex))
            merged = twse + tpex
            twse_d = {s["trade_date"] for s in twse if s.get("trade_date")}
            tpex_d = {s["trade_date"] for s in tpex if s.get("trade_date")}
            if twse_d or tpex_d:
                logger.info(
                    "Market trade_date: TWSE=%s, TPEx=%s",
                    sorted(twse_d),
                    sorted(tpex_d),
                )
            return merged
        finally:
            if close_after:
                await session.close()
