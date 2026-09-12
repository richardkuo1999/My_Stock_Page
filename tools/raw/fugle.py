"""fugle — 富果 (Fugle) marketdata 原始資料 function 集（CLI + import 雙入口）

讀 .env 的 FUGLE_API_KEY，header X-API-KEY。個股類 endpoint 皆可用；
snapshot（全市場）需更高權限，本工具不含。

用法:
  python tools/raw/fugle.py --quote 2330          # 即時報價（含五檔 bids/asks）
  python tools/raw/fugle.py --ticker 2330         # 交易屬性（漲跌停/產業/可否當沖）
  python tools/raw/fugle.py --intraday-candles 2330   # 當日分鐘K
  python tools/raw/fugle.py --trades 2330         # 當日成交明細
  python tools/raw/fugle.py --volumes 2330        # 當日分價量
  python tools/raw/fugle.py --candles 2330 [--days N]  # 歷史日K
  python tools/raw/fugle.py --stats 2330          # 52週高低/成交統計

回傳: JSON（Fugle 原始 payload）或 {"error"}。
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FUGLE_BASE = "https://api.fugle.tw/marketdata/v1.0/stock"
DEFAULT_TIMEOUT = 15.0


def _get_key() -> str | None:
    key = os.getenv("FUGLE_API_KEY", "").strip().strip('"').strip("'")
    return key if key else None


async def _get(path: str, params: dict | None = None) -> dict:
    """GET 一個 Fugle endpoint，回原始 payload（dict）或 {"error"}。"""
    key = _get_key()
    if not key:
        return {"error": "未設定 FUGLE_API_KEY"}
    url = f"{FUGLE_BASE}/{path}"
    headers = {"X-API-KEY": key, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params=params)
            if r.status_code != 200:
                return {"error": f"Fugle {path} HTTP {r.status_code}"}
            return r.json()
    except Exception as e:
        logger.debug("Fugle %s error: %s", path, e)
        return {"error": f"Fugle {path} 請求失敗: {e}"}


async def fetch_quote(symbol: str) -> dict:
    """即時報價（含五檔委買賣、成交統計）。"""
    return await _get(f"intraday/quote/{symbol}")


async def fetch_ticker(symbol: str) -> dict:
    """交易屬性（漲跌停價、產業別、可否當沖、處置/注意）。"""
    return await _get(f"intraday/ticker/{symbol}")


async def fetch_intraday_candles(symbol: str) -> dict:
    """當日分鐘K。"""
    return await _get(f"intraday/candles/{symbol}")


async def fetch_trades(symbol: str) -> dict:
    """當日成交明細。"""
    return await _get(f"intraday/trades/{symbol}")


async def fetch_volumes(symbol: str) -> dict:
    """當日分價量（各價位成交量）。"""
    return await _get(f"intraday/volumes/{symbol}")


# Fugle historical/candles 單次查詢範圍上限約一年，超過會 HTTP 400。
# 用略小於一年的分段（避免邊界）逐段查再合併。
_CANDLE_CHUNK_DAYS = 360


async def fetch_historical_candles(symbol: str, days: int = 365) -> dict:
    """歷史日K（OHLCV）。超過一年自動分段查詢再合併（Fugle 單次上限約一年）。"""
    end = datetime.now()
    start = end - timedelta(days=days)

    all_rows: list[dict] = []
    meta: dict = {}
    seg_end = end
    while seg_end > start:
        seg_start = max(start, seg_end - timedelta(days=_CANDLE_CHUNK_DAYS))
        params = {
            "from": seg_start.strftime("%Y-%m-%d"),
            "to": seg_end.strftime("%Y-%m-%d"),
            "timeframe": "D",
            "fields": "open,high,low,close,volume",
            "sort": "asc",
        }
        res = await _get(f"historical/candles/{symbol}", params=params)
        if "error" in res:
            # 第一段就失敗才視為錯誤；後續段失敗則用已取得的資料
            if not all_rows:
                return res
            break
        if not meta:
            meta = {k: v for k, v in res.items() if k != "data"}
        all_rows.extend(res.get("data", []) or [])
        # 下一段結束日 = 這段起點的前一天
        seg_end = seg_start - timedelta(days=1)

    # 依日期去重 + 排序（分段邊界可能重疊）
    by_date = {r.get("date"): r for r in all_rows if r.get("date")}
    merged = [by_date[d] for d in sorted(by_date)]
    result = dict(meta)
    result["symbol"] = symbol
    result["data"] = merged
    if not merged:
        return {"error": f"Fugle 無歷史K線: {symbol}"}
    return result


async def fetch_stats(symbol: str) -> dict:
    """成交統計（含 52 週高低、成交量值）。"""
    return await _get(f"historical/stats/{symbol}")


_MODES = {
    "quote": fetch_quote,
    "ticker": fetch_ticker,
    "intraday-candles": fetch_intraday_candles,
    "trades": fetch_trades,
    "volumes": fetch_volumes,
    "candles": fetch_historical_candles,
    "stats": fetch_stats,
}


def _parse_args(argv: list[str]) -> tuple[str, str, int]:
    mode = None
    symbol = None
    days = 365
    for flag in _MODES:
        if f"--{flag}" in argv:
            mode = flag
            idx = argv.index(f"--{flag}")
            if idx + 1 < len(argv):
                symbol = argv[idx + 1]
            break
    if "--days" in argv:
        try:
            days = int(argv[argv.index("--days") + 1])
        except (IndexError, ValueError):
            pass
    return mode, symbol, days


async def _run(mode: str, symbol: str, days: int) -> dict:
    fn = _MODES[mode]
    if mode == "candles":
        return await fn(symbol, days)
    return await fn(symbol)


if __name__ == "__main__":
    args = sys.argv[1:]
    mode, symbol, days = _parse_args(args)
    if not mode or not symbol:
        flags = "|".join(f"--{m}" for m in _MODES)
        print(json.dumps({"error": f"用法: python tools/raw/fugle.py [{flags}] SYMBOL [--days N]"},
                         ensure_ascii=False))
        sys.exit(1)

    result = asyncio.run(_run(mode, symbol, days))
    print(json.dumps(result, ensure_ascii=False))
    if isinstance(result, dict) and "error" in result:
        sys.exit(1)
