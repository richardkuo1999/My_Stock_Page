"""
富果 Fugle Market Data REST API（HTTP）
文件：https://developer.fugle.tw/docs/data/http-api/getting-started/
請在請求標頭帶入 X-API-KEY。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

BASE = "https://api.fugle.tw/marketdata/v1.0/stock"
DEFAULT_TIMEOUT = 30.0


def _api_key() -> str | None:
    k = (get_settings().FUGLE_API_KEY or "").strip()
    return k.strip('"').strip("'") if k else None


def fugle_api_key_configured() -> bool:
    """是否已設定富果 API 金鑰（用於爆量偵測等選用功能）。"""
    return bool(_api_key())


def _headers() -> dict[str, str]:
    key = _api_key()
    if not key:
        raise RuntimeError("未設定 FUGLE_API_KEY（.env 或環境變數）")
    return {"X-API-KEY": key, "Accept": "application/json"}


async def historical_candles_daily(
    symbol: str,
    date_from: str,
    date_to: str,
    *,
    adjusted: str = "false",
    sort: str = "asc",
) -> dict[str, Any]:
    """
    GET /historical/candles/{symbol}，日 K（timeframe=D）。
    日期格式 yyyy-MM-dd；欄位含 volume（股）、close 等。
    文件：https://developer.fugle.tw/docs/data/http-api/historical/candles/
    """
    url = f"{BASE}/historical/candles/{symbol}"
    params: dict[str, str] = {
        "from": date_from,
        "to": date_to,
        "timeframe": "D",
        "fields": "open,high,low,close,volume,change",
        "adjusted": adjusted,
        "sort": sort,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        r = await client.get(url, headers=_headers(), params=params)
        r.raise_for_status()
        return r.json()


async def intraday_ticker(symbol: str) -> dict[str, Any]:
    """GET /intraday/ticker/{symbol}，例如 symbol=2330。"""
    url = f"{BASE}/intraday/ticker/{symbol}"
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        r = await client.get(url, headers=_headers())
        r.raise_for_status()
        return r.json()


async def intraday_quote(symbol: str) -> dict[str, Any]:
    """GET /intraday/quote/{symbol} — 即時報價。"""
    url = f"{BASE}/intraday/quote/{symbol}"
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        r = await client.get(url, headers=_headers())
        r.raise_for_status()
        return r.json()


async def test_connection(symbol: str = "2330") -> tuple[bool, str]:
    """
    測試金鑰是否可用。成功回傳 (True, 簡短說明)；失敗 (False, 錯誤訊息，不含金鑰)。
    """
    try:
        data = await intraday_ticker(symbol)
        name = data.get("name", "?")
        sym = data.get("symbol", symbol)
        return True, f"OK：{sym} {name}"
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        body = ""
        try:
            body = (e.response.text or "")[:200]
        except Exception:
            pass
        logger.warning("Fugle HTTP %s: %s", code, body)
        return False, f"HTTP {code}（請確認方案與權限；勿將金鑰提交版控）"
    except Exception as e:
        logger.exception("Fugle 連線失敗")
        return False, str(e)[:200]
