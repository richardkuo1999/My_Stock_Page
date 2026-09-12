"""analysis.fundamentals — 即時基本面摘要（call raw/uanalyze，best-effort）。

主要消費者：get_stock_price.py 的 /p，把基本面 best-effort 疊在價量上。
資料來源：raw/uanalyze 的 web_stock_info（收盤/漲跌幅/最新財報/月營收/掛牌類別）
         + historical_per（本益比，取最新一月）。

best-effort：任何失敗/無憑證都回 {}（不是 error dict），因為 /p 拿到價量就要回，
基本面只是加分。
"""

import asyncio
import json
import logging
import sys

try:
    from tools.raw import uanalyze as raw_uanalyze
except ImportError:  # pragma: no cover - CLI standalone fallback
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
    from tools.raw import uanalyze as raw_uanalyze

logger = logging.getLogger(__name__)

# WebStockInfo 的 ChineseAccount → 我們挑用的基本面欄位名。
_WEBSTOCKINFO_FIELDS = {
    "收盤價": "收盤價",
    "當日漲跌幅": "當日漲跌幅(%)",
    "最新財報": "最新財報",
    "月營收": "最新月營收",
    "掛牌類別": "掛牌類別",
}


async def fetch_stock_fundamentals(symbol: str) -> dict:
    """即時基本面摘要（best-effort，回 {} 而非 error）。call raw web_stock_info + historical_per。"""
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {}

    summary: dict = {}

    # WebStockInfo：基本市況欄位
    try:
        rows = await raw_uanalyze.fetch_raw_web_stock_info(symbol)
        if isinstance(rows, dict) and "error" not in rows:
            for row in rows.values():
                if not isinstance(row, dict):
                    continue
                label = row.get("ChineseAccount", "")
                if label in _WEBSTOCKINFO_FIELDS:
                    value = row.get("Data")
                    if isinstance(value, (int, float, str)) and value not in ("", None):
                        summary[_WEBSTOCKINFO_FIELDS[label]] = value
    except Exception as e:
        logger.warning("fetch_stock_fundamentals WebStockInfo failed for %s: %s", symbol, e)

    # HistoricalPer：本益比（取最新一月）
    try:
        per = await raw_uanalyze.fetch_raw_historical_per(symbol)
        if isinstance(per, dict) and "error" not in per:
            for row in per.values():
                if isinstance(row, dict) and "本益比" in row.get("ChineseAccount", ""):
                    data = row.get("Data", {})
                    if isinstance(data, dict) and data:
                        latest_key = sorted(data.keys())[-1]
                        summary["本益比"] = data[latest_key]
                    break
    except Exception as e:
        logger.warning("fetch_stock_fundamentals HistoricalPer failed for %s: %s", symbol, e)

    return summary


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "用法: python tools/analysis/fundamentals.py <代號>"}, ensure_ascii=False))
        sys.exit(1)
    result = asyncio.run(fetch_stock_fundamentals(args[0]))
    print(json.dumps(result, ensure_ascii=False))
