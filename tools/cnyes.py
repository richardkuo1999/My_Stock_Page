"""cnyes — 鉅亨網 (CNYES) 原始資料 function 集（CLI + import 雙入口）

無需授權，加瀏覽器 UA + Origin/Referer 即可用。symbol 用純代號（2330），
內部自動轉成 CNYES 格式 TWS:2330:STOCK（上櫃 5 碼以 OTC 前綴，見 _to_sym）。

用法:
  python tools/cnyes.py --eps 2330        # FactSet 各年度預估 EPS
  python tools/cnyes.py --target 2330     # 分析師目標價共識
  python tools/cnyes.py --quote 2330      # 即時報價（數字代碼欄位已解碼）
  python tools/cnyes.py --candles 2330 [--days N]   # 歷史日K線

回傳: JSON。失敗時 {"error": "..."}。
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

MARKETINFO_BASE = "https://marketinfo.api.cnyes.com/mi/api/v1"
WS_BASE = "https://ws.api.cnyes.com/ws/api/v1"
DEFAULT_TIMEOUT = 15.0

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Origin": "https://invest.cnyes.com",
    "Referer": "https://invest.cnyes.com/",
    "Accept": "application/json",
}

# 即時報價 quote/quotes 的數字代碼欄位對照（實測 2330 推得）
_QUOTE_FIELD_MAP = {
    "200009": "name",
    "200010": "symbol",
    "6": "close",
    "11": "change",
    "56": "change_pct",
    "12": "open",
    "19": "high",
    "21": "low",
    "13": "prev_close",
    "75": "limit_up",
    "76": "limit_down",
    "800001": "volume",
    "200067": "trade_value",
    "200007": "time",
    "800043": "url",
}


def _to_sym(symbol: str) -> str:
    """把純代號轉成 CNYES symbolId。4 碼→TWS（上市），5 碼→OTC（上櫃）。

    註：多數 ETF/上市為 4 碼走 TWS；5 碼多為上櫃走 OTC。已含前綴則原樣回傳。
    """
    s = symbol.strip().upper()
    if ":" in s:
        return s
    market = "OTC" if len(s) >= 5 else "TWS"
    return f"{market}:{s}:STOCK"


async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> dict | None:
    """GET 一個 CNYES JSON endpoint，回 payload（dict）或 None。"""
    try:
        r = await client.get(url, headers=_HEADERS, params=params)
        if r.status_code != 200:
            logger.debug("CNYES %s -> HTTP %d", url, r.status_code)
            return None
        return r.json()
    except Exception as e:
        logger.debug("CNYES request error %s: %s", url, e)
        return None


async def fetch_estimate_eps(symbol: str) -> dict:
    """FactSet 各年度預估 EPS。

    Returns dict:
      {"symbol", "data": [{financial_year, rate_date, eps_mean, eps_median,
       eps_high, eps_low, num_est, up, down, std_dev}...]} 或 {"error"}
    """
    sym = _to_sym(symbol)
    url = f"{MARKETINFO_BASE}/financialIndicator/estimateProfit/{sym}?type=eps"
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        payload = await _get_json(client, url)
    if not payload or payload.get("statusCode") != 200 or not payload.get("data"):
        return {"error": f"CNYES 預估EPS查無資料: {symbol}"}

    items = []
    for it in payload["data"]:
        if not isinstance(it, dict):
            continue
        items.append({
            "financial_year": it.get("financialYear"),
            "rate_date": it.get("rateDate"),
            "eps_mean": it.get("feMean"),
            "eps_median": it.get("feMedian"),
            "eps_high": it.get("feHigh"),
            "eps_low": it.get("feLow"),
            "num_est": it.get("numEst"),
            "up": it.get("feUp"),
            "down": it.get("feDown"),
            "std_dev": it.get("feStdDev"),
            "currency": it.get("currency"),
        })
    items.sort(key=lambda x: x.get("financial_year") or 0)
    return {"symbol": symbol, "data": items}


async def fetch_target_price(symbol: str) -> dict:
    """分析師目標價共識。

    Returns dict with target_mean/median/high/low, num_est, up, down,
    std_dev, last(現價), upside_pct(相對現價的均價上漲空間) 或 {"error"}.
    """
    sym = _to_sym(symbol)
    url = f"{MARKETINFO_BASE}/financialIndicator/targetPrice/{sym}"
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        payload = await _get_json(client, url)
    if not payload or payload.get("statusCode") != 200 or not payload.get("data"):
        return {"error": f"CNYES 目標價查無資料: {symbol}"}

    d = payload["data"]
    last = d.get("last")
    mean = d.get("feMean")
    upside = None
    if isinstance(last, (int, float)) and isinstance(mean, (int, float)) and last:
        upside = round((mean - last) / last * 100, 2)
    return {
        "symbol": symbol,
        "name": d.get("chName"),
        "rate_date": d.get("rateDate"),
        "target_mean": mean,
        "target_median": d.get("feMedian"),
        "target_high": d.get("feHigh"),
        "target_low": d.get("feLow"),
        "num_est": d.get("numEst"),
        "up": d.get("feUp"),
        "down": d.get("feDown"),
        "std_dev": d.get("feStdDev"),
        "last": last,
        "upside_pct": upside,
        "currency": d.get("currency"),
    }


def _decode_quote(raw: dict) -> dict:
    """把數字代碼欄位的即時報價解成可讀鍵。未知代碼保留原鍵。"""
    out = {}
    for k, v in raw.items():
        out[_QUOTE_FIELD_MAP.get(str(k), str(k))] = v
    return out


async def fetch_quote(symbol: str) -> dict:
    """CNYES 即時報價（數字代碼欄位已解碼）。"""
    sym = _to_sym(symbol)
    url = f"{WS_BASE}/quote/quotes/{sym}"
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        payload = await _get_json(client, url)
    if not payload or payload.get("statusCode") != 200 or not payload.get("data"):
        return {"error": f"CNYES 報價查無資料: {symbol}"}
    rows = payload["data"]
    if not rows:
        return {"error": f"CNYES 報價查無資料: {symbol}"}
    decoded = _decode_quote(rows[0])
    decoded["symbol_input"] = symbol
    return decoded


async def fetch_history(symbol: str, days: int = 365) -> dict:
    """歷史日K線。回 {"symbol", "candles": [{date, open, high, low, close, volume}...]}。"""
    sym = _to_sym(symbol)
    now = datetime.now()
    frm = now - timedelta(days=days)
    url = f"{WS_BASE}/charting/history"
    params = {
        "symbol": sym,
        "resolution": "D",
        "from": int(frm.timestamp()),
        "to": int(now.timestamp()),
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        payload = await _get_json(client, url, params=params)
    if not payload or payload.get("statusCode") != 200:
        return {"error": f"CNYES 歷史K線查無資料: {symbol}"}
    data = payload.get("data", {})
    t = data.get("t", []) or []
    o = data.get("o", []) or []
    h = data.get("h", []) or []
    low = data.get("l", []) or []
    c = data.get("c", []) or []
    v = data.get("v", []) or []
    candles = []
    for i in range(len(t)):
        candles.append({
            "date": datetime.fromtimestamp(t[i]).strftime("%Y-%m-%d"),
            "open": o[i] if i < len(o) else None,
            "high": h[i] if i < len(h) else None,
            "low": low[i] if i < len(low) else None,
            "close": c[i] if i < len(c) else None,
            "volume": v[i] if i < len(v) else None,
        })
    if not candles:
        return {"error": f"CNYES 歷史K線查無資料: {symbol}"}
    return {"symbol": symbol, "candles": candles}


def _parse_args(argv: list[str]) -> tuple[str, str, int]:
    """回 (mode, symbol, days)。mode 為 eps/target/quote/candles。"""
    mode = None
    symbol = None
    days = 365
    for flag in ("--eps", "--target", "--quote", "--candles"):
        if flag in argv:
            mode = flag[2:]
            idx = argv.index(flag)
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
    if mode == "eps":
        return await fetch_estimate_eps(symbol)
    if mode == "target":
        return await fetch_target_price(symbol)
    if mode == "quote":
        return await fetch_quote(symbol)
    if mode == "candles":
        return await fetch_history(symbol, days)
    return {"error": "未知模式"}


if __name__ == "__main__":
    args = sys.argv[1:]
    mode, symbol, days = _parse_args(args)
    if not mode or not symbol:
        print(json.dumps({
            "error": "用法: python tools/cnyes.py [--eps|--target|--quote|--candles] SYMBOL [--days N]"
        }, ensure_ascii=False))
        sys.exit(1)

    result = asyncio.run(_run(mode, symbol, days))
    print(json.dumps(result, ensure_ascii=False))
    if isinstance(result, dict) and "error" in result:
        sys.exit(1)
