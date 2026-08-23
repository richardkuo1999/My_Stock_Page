"""get_stock_price — 查詢即時/收盤股價
用法: python tools/get_stock_price.py SYMBOL
回傳: JSON {"symbol": str, "name": str, "price": float, "change": float, "change_pct": float, "volume": int}
"""

import asyncio
import json
import logging
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# FinMind API
FINMIND_TICK_URL = "https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot"

# Fugle API
FUGLE_BASE = "https://api.fugle.tw/marketdata/v1.0/stock"

DEFAULT_TIMEOUT = 15.0
# UAnalyze 基本面附加抓取的短逾時（best-effort，不能拖累價量秒回）。
FUNDAMENTALS_TIMEOUT = 8.0


def _get_finmind_tokens() -> list[str]:
    """Parse FINMIND_TOKENS env var (JSON array string or single token)."""
    raw = os.getenv("FINMIND_TOKENS", "")
    if not raw:
        return []
    try:
        tokens = json.loads(raw)
        return tokens if isinstance(tokens, list) else []
    except json.JSONDecodeError:
        return [raw] if raw else []


def _get_fugle_api_key() -> str | None:
    """Get Fugle API key from env."""
    key = os.getenv("FUGLE_API_KEY", "").strip().strip('"').strip("'")
    return key if key else None


_token_index = 0


def _next_finmind_token() -> str | None:
    """Round-robin through available FinMind tokens."""
    global _token_index
    tokens = _get_finmind_tokens()
    if not tokens:
        return None
    token = tokens[_token_index % len(tokens)]
    _token_index += 1
    return token


async def _fetch_fugle(symbol: str) -> dict | None:
    """Try Fugle intraday quote API."""
    key = _get_fugle_api_key()
    if not key:
        return None
    url = f"{FUGLE_BASE}/intraday/quote/{symbol}"
    headers = {"X-API-KEY": key, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return None
            data = r.json()
            price = data.get("closePrice") or data.get("lastPrice") or data.get("previousClose")
            if price is None:
                return None
            prev = data.get("previousClose") or data.get("referencePrice")
            change = data.get("change")
            change_pct = data.get("changePercent")
            if change is None and prev and price:
                change = round(price - prev, 2)
            if change_pct is None and prev and change is not None:
                change_pct = round((change / prev) * 100, 2)
            return {
                "symbol": symbol,
                "name": data.get("name", symbol),
                "price": float(price),
                "change": float(change) if change is not None else 0.0,
                "change_pct": float(change_pct) if change_pct is not None else 0.0,
                "volume": int(data.get("tradeVolume") or data.get("volume") or 0),
                "source": "fugle",
            }
    except Exception as e:
        logger.debug("Fugle fetch error for %s: %s", symbol, e)
        return None


async def _fetch_finmind(symbol: str) -> dict | None:
    """Try FinMind tick snapshot API with token rotation on 402/403."""
    token = _next_finmind_token()
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    params = {"data_id": symbol}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(FINMIND_TICK_URL, headers=headers, params=params)
            if r.status_code in (402, 403):
                # Token exhausted — try next one
                token = _next_finmind_token()
                if token:
                    headers = {"Authorization": f"Bearer {token}"}
                    r = await client.get(FINMIND_TICK_URL, headers=headers, params=params)
            if r.status_code != 200:
                return None
            data = r.json()
            rows = data.get("data", [])
            if not rows:
                return None
            row = rows[0]
            close = row.get("close")
            if close is None:
                return None
            change = row.get("change_price")
            change_rate = row.get("change_rate")
            return {
                "symbol": symbol,
                "name": row.get("stock_name", symbol),
                "price": float(close),
                "change": float(change) if change is not None else 0.0,
                "change_pct": float(change_rate) if change_rate is not None else 0.0,
                "volume": int(row.get("volume", 0)),
                "source": "finmind",
            }
    except Exception as e:
        logger.debug("FinMind fetch error for %s: %s", symbol, e)
        return None


async def _augment_fundamentals(result: dict) -> None:
    """Best-effort：補打 UAnalyze 基本面附在 result['fundamentals']（形態 a1）。

    **鐵則：這是加分項，絕不能拖累/影響價量。** 用短 timeout + asyncio.wait_for
    防拖，整段包在獨立 try，任何 Exception/逾時都吞掉 → 基本面略過，價量照常回。

    fetch_stock_fundamentals 在 tools/uanalyze.py，用局部 import（tools.* 優先、
    直接 import 後援），讓 get_stock_price.py 當獨立 CLI 跑時也能載入。
    """
    try:
        try:
            from tools.uanalyze import fetch_stock_fundamentals
        except ImportError:
            from uanalyze import fetch_stock_fundamentals  # CLI standalone fallback

        symbol = result.get("symbol", "")
        fundamentals = await asyncio.wait_for(
            fetch_stock_fundamentals(symbol), timeout=FUNDAMENTALS_TIMEOUT
        )
        if fundamentals:
            result["fundamentals"] = fundamentals
    except Exception as e:
        # 逾時/失敗/無憑證：略過基本面，價量不受影響。
        logger.debug("Fundamentals augment skipped for %s: %s", result.get("symbol"), e)


async def fetch_price(symbol: str) -> dict:
    """Fetch stock price. Try Fugle first (real-time), then FinMind.

    Args:
        symbol: Taiwan stock symbol, e.g. '2330', '00878'

    Returns:
        dict with symbol, name, price, change, change_pct, volume, source
        （成功時另 best-effort 附 'fundamentals'；UAnalyze 失敗則無此鍵）
        On failure: dict with 'error' key
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}

    # 1. Try Fugle (real-time)
    result = await _fetch_fugle(symbol)

    # 2. Try FinMind
    if not result:
        result = await _fetch_finmind(symbol)

    if not result:
        return {"error": f"找不到股票代號 {symbol}"}

    # 價量已到手 → best-effort 疊加 UAnalyze 基本面（絕不影響上面的價量回傳）。
    await _augment_fundamentals(result)
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "用法: python tools/get_stock_price.py SYMBOL"}, ensure_ascii=False))
        sys.exit(1)

    symbol = sys.argv[1]
    result = asyncio.run(fetch_price(symbol))
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
