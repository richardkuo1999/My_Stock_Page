"""get_stock_price — 查詢即時/收盤股價
用法: python tools/analysis/get_stock_price.py SYMBOL
回傳: JSON {"symbol": str, "name": str, "price": float, "change": float, "change_pct": float, "volume": int}
"""

import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

# 直接跑 python tools/analysis/get_stock_price.py 時補 repo 根到 sys.path，
# 以便 import tools.raw.* / tools.analysis.fundamentals。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools.raw import finmind as raw_finmind
from tools.raw import fugle as raw_fugle

load_dotenv()
logger = logging.getLogger(__name__)

# UAnalyze 基本面附加抓取的短逾時（best-effort，不能拖累價量秒回）。
FUNDAMENTALS_TIMEOUT = 8.0


async def _fetch_fugle(symbol: str) -> dict | None:
    """Fugle 即時報價（委派 raw/fugle），抽欄位 + 算漲跌（analysis 加工）。"""
    data = await raw_fugle.fetch_quote(symbol)
    if not isinstance(data, dict) or "error" in data:
        return None
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
    # Fugle 把成交量放在 total.tradeVolume；頂層 tradeVolume/volume 通常為空。
    total = data.get("total") or {}
    volume = total.get("tradeVolume") or data.get("tradeVolume") or data.get("volume") or 0
    return {
        "symbol": symbol,
        "name": data.get("name", symbol),
        "price": float(price),
        "change": float(change) if change is not None else 0.0,
        "change_pct": float(change_pct) if change_pct is not None else 0.0,
        "volume": int(volume),
        "source": "fugle",
    }


async def _fetch_finmind(symbol: str) -> dict | None:
    """FinMind tick 快照（委派 raw/finmind，token 輪替在 raw 層），抽欄位。"""
    data = await asyncio.to_thread(raw_finmind.fetch_tick_snapshot, symbol)
    if not isinstance(data, dict) or "error" in data:
        return None
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


async def _augment_fundamentals(result: dict) -> None:
    """Best-effort：補打 UAnalyze 基本面附在 result['fundamentals']（形態 a1）。

    **鐵則：這是加分項，絕不能拖累/影響價量。** 用短 timeout + asyncio.wait_for
    防拖，整段包在獨立 try，任何 Exception/逾時都吞掉 → 基本面略過，價量照常回。

    fetch_stock_fundamentals 在 tools/analysis/fundamentals.py，用局部 import（tools.* 優先、
    直接 import 後援），讓 get_stock_price.py 當獨立 CLI 跑時也能載入。
    """
    try:
        from tools.analysis.fundamentals import fetch_stock_fundamentals

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
        print(json.dumps({"error": "用法: python tools/analysis/get_stock_price.py SYMBOL"}, ensure_ascii=False))
        sys.exit(1)

    symbol = sys.argv[1]
    result = asyncio.run(fetch_price(symbol))
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
