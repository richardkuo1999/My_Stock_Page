"""yfinance_data — Yahoo Finance (yfinance) 原始資料 function 集（CLI + import 雙入口）

台股代號自動補 .TW，失敗再試 .TWO（上櫃）。yfinance 為同步庫，以 asyncio.to_thread
包成 async 供其他 async 工具 import。

用法:
  python tools/raw/yfinance_data.py --info 2330        # 精選基本面欄位
  python tools/raw/yfinance_data.py --target 2330      # 分析師目標價 + 評等
  python tools/raw/yfinance_data.py --history 2330 [--period 1y]  # 歷史價
  python tools/raw/yfinance_data.py --financials 2330  # 年度損益表

回傳: JSON 或 {"error"}。
"""

import asyncio
import json
import logging
import sys

logger = logging.getLogger(__name__)

# info 中要保留的精選欄位（169 欄太多）
_INFO_KEYS = [
    "longName", "shortName", "symbol", "currentPrice", "previousClose",
    "marketCap", "sector", "industry", "trailingPE", "forwardPE",
    "priceToBook", "trailingEps", "forwardEps", "dividendYield",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "currency",
]

_TARGET_KEYS = [
    "currentPrice", "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    "targetMedianPrice", "numberOfAnalystOpinions", "recommendationKey",
    "recommendationMean",
]


def _resolve_ticker(symbol: str):
    """把台股純代號解析成能拿到資料的 yf.Ticker（先試 .TW 再 .TWO）。

    已含 '.' 的代號原樣使用。回 (ticker, resolved_symbol) 或 (None, None)。
    """
    import yfinance as yf

    s = symbol.strip().upper()
    candidates = [s] if "." in s else [f"{s}.TW", f"{s}.TWO"]
    for cand in candidates:
        try:
            t = yf.Ticker(cand)
            info = t.info or {}
            # 有 currentPrice 或 regularMarketPrice 視為有效
            if info.get("currentPrice") or info.get("regularMarketPrice"):
                return t, cand
        except Exception as e:
            logger.debug("yfinance resolve %s failed: %s", cand, e)
            continue
    return None, None


def _fetch_info_sync(symbol: str) -> dict:
    t, resolved = _resolve_ticker(symbol)
    if t is None:
        return {"error": f"yfinance 查無資料: {symbol}"}
    info = t.info or {}
    out = {"symbol": symbol, "resolved": resolved}
    for k in _INFO_KEYS:
        out[k] = info.get(k)
    return out


def _fetch_target_sync(symbol: str) -> dict:
    t, resolved = _resolve_ticker(symbol)
    if t is None:
        return {"error": f"yfinance 查無資料: {symbol}"}
    info = t.info or {}
    out = {"symbol": symbol, "resolved": resolved}
    for k in _TARGET_KEYS:
        out[k] = info.get(k)
    cur = info.get("currentPrice")
    mean = info.get("targetMeanPrice")
    if isinstance(cur, (int, float)) and isinstance(mean, (int, float)) and cur:
        out["upside_pct"] = round((mean - cur) / cur * 100, 2)
    return out


def _fetch_history_sync(symbol: str, period: str) -> dict:
    t, resolved = _resolve_ticker(symbol)
    if t is None:
        return {"error": f"yfinance 查無資料: {symbol}"}
    try:
        h = t.history(period=period)
    except Exception as e:
        return {"error": f"yfinance 歷史價失敗: {e}"}
    if h is None or h.empty:
        return {"error": f"yfinance 無歷史價: {symbol}"}
    rows = []
    for idx, row in h.iterrows():
        rows.append({
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        })
    return {"symbol": symbol, "resolved": resolved, "period": period, "history": rows}


def _fetch_financials_sync(symbol: str) -> dict:
    t, resolved = _resolve_ticker(symbol)
    if t is None:
        return {"error": f"yfinance 查無資料: {symbol}"}
    try:
        fin = t.financials
    except Exception as e:
        return {"error": f"yfinance 財報失敗: {e}"}
    if fin is None or fin.empty:
        return {"error": f"yfinance 無財報: {symbol}"}
    # columns 是各期日期，index 是科目
    out = {}
    for col in fin.columns:
        key = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
        col_data = {}
        for idx, val in fin[col].items():
            try:
                col_data[str(idx)] = None if val != val else float(val)  # NaN 檢查
            except (TypeError, ValueError):
                col_data[str(idx)] = None
        out[key] = col_data
    return {"symbol": symbol, "resolved": resolved, "financials": out}


# ── async 包裝（供其他 async 工具 import）────────────────────────────

async def fetch_info(symbol: str) -> dict:
    return await asyncio.to_thread(_fetch_info_sync, symbol)


async def fetch_target(symbol: str) -> dict:
    return await asyncio.to_thread(_fetch_target_sync, symbol)


async def fetch_history(symbol: str, period: str = "1y") -> dict:
    return await asyncio.to_thread(_fetch_history_sync, symbol, period)


async def fetch_financials(symbol: str) -> dict:
    return await asyncio.to_thread(_fetch_financials_sync, symbol)


_MODES = {"info": fetch_info, "target": fetch_target,
          "history": fetch_history, "financials": fetch_financials}


def _parse_args(argv: list[str]) -> tuple[str, str, str]:
    mode = None
    symbol = None
    period = "1y"
    for flag in _MODES:
        if f"--{flag}" in argv:
            mode = flag
            idx = argv.index(f"--{flag}")
            if idx + 1 < len(argv):
                symbol = argv[idx + 1]
            break
    if "--period" in argv:
        try:
            period = argv[argv.index("--period") + 1]
        except IndexError:
            pass
    return mode, symbol, period


async def _run(mode: str, symbol: str, period: str) -> dict:
    if mode == "history":
        return await fetch_history(symbol, period)
    return await _MODES[mode](symbol)


if __name__ == "__main__":
    args = sys.argv[1:]
    mode, symbol, period = _parse_args(args)
    if not mode or not symbol:
        flags = "|".join(f"--{m}" for m in _MODES)
        print(json.dumps({"error": f"用法: python tools/raw/yfinance_data.py [{flags}] SYMBOL [--period 1y]"},
                         ensure_ascii=False))
        sys.exit(1)

    result = asyncio.run(_run(mode, symbol, period))
    print(json.dumps(result, ensure_ascii=False))
    if isinstance(result, dict) and "error" in result:
        sys.exit(1)
