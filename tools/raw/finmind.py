"""finmind — FinMind 原始資料 function 集（CLI + import 雙入口）

讀 .env 的 FINMIND_TOKENS（JSON 陣列字串或單一 token），token round-robin。
macOS 常見 SSL 憑證問題，httpx 用 verify=False（沿用專案既有做法）。

每個 dataset 一個 function，回原始 rows（list[dict]）；CLI 用子命令對應。

用法:
  python tools/raw/finmind.py --per 2330 [--start 2023-01-01]      # 本益比/淨值比/殖利率
  python tools/raw/finmind.py --price 2330 [--start ...]           # 日收盤價量
  python tools/raw/finmind.py --revenue 2330                       # 月營收
  python tools/raw/finmind.py --income 2330                        # 綜合損益表
  python tools/raw/finmind.py --balance 2330                       # 資產負債表
  python tools/raw/finmind.py --cashflow 2330                      # 現金流量表
  python tools/raw/finmind.py --dividend 2330                      # 股利政策
  python tools/raw/finmind.py --institution 2330                   # 法人買賣超
  python tools/raw/finmind.py --margin 2330                        # 融資融券
  python tools/raw/finmind.py --shareholding 2330                  # 外資持股
  python tools/raw/finmind.py --info 2330                          # 基本資料
  python tools/raw/finmind.py --news 2330                          # 相關新聞
  python tools/raw/finmind.py --snapshot 2330                      # 即時 tick 快照（另一端點）

回傳: JSON {"dataset", "data_id", "data": [...]} 或 {"error"}。
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TICK_SNAPSHOT_URL = "https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot"
DEFAULT_TIMEOUT = 25.0

# CLI flag → (dataset, 是否需要 start_date)
_MODE_DATASET = {
    "per": "TaiwanStockPER",
    "price": "TaiwanStockPrice",
    "revenue": "TaiwanStockMonthRevenue",
    "income": "TaiwanStockFinancialStatements",
    "balance": "TaiwanStockBalanceSheet",
    "cashflow": "TaiwanStockCashFlowsStatement",
    "dividend": "TaiwanStockDividend",
    "institution": "TaiwanStockInstitutionalInvestorsBuySell",
    "margin": "TaiwanStockMarginPurchaseShortSale",
    "shareholding": "TaiwanStockShareholding",
    "info": "TaiwanStockInfo",
    "news": "TaiwanStockNews",
}

_token_index = 0


def _get_tokens() -> list[str]:
    """Parse FINMIND_TOKENS（JSON 陣列字串或單一 token）。"""
    raw = os.getenv("FINMIND_TOKENS", "").strip()
    if not raw:
        return []
    try:
        tokens = json.loads(raw)
        return [t for t in tokens if t] if isinstance(tokens, list) else [raw]
    except json.JSONDecodeError:
        return [raw.strip('"').strip("'")]


def _next_token() -> str:
    """Round-robin 取下一個 token；無 token 回空字串（FinMind 匿名有較低額度）。"""
    global _token_index
    tokens = _get_tokens()
    if not tokens:
        return ""
    tok = tokens[_token_index % len(tokens)]
    _token_index += 1
    return tok


def _default_start(days: int = 365) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def fetch_dataset(dataset: str, data_id: str, start_date: str | None = None) -> dict:
    """通用 FinMind dataset 抓取。回 {"dataset","data_id","data":[...]} 或 {"error"}。

    402/該 token 額度用盡時，換下一個 token 重試一次。
    """
    params = {"dataset": dataset, "data_id": data_id, "token": _next_token()}
    if start_date:
        params["start_date"] = start_date

    try:
        # verify=False：macOS Python 憑證鏈常缺 issuer，沿用專案既有處理
        with httpx.Client(timeout=DEFAULT_TIMEOUT, verify=False) as client:
            r = client.get(FINMIND_URL, params=params)
            if r.status_code == 402:  # 額度用盡 → 換 token 再試
                params["token"] = _next_token()
                r = client.get(FINMIND_URL, params=params)
            if r.status_code != 200:
                return {"error": f"FinMind {dataset} HTTP {r.status_code}: {data_id}"}
            payload = r.json()
    except Exception as e:
        logger.debug("FinMind %s error: %s", dataset, e)
        return {"error": f"FinMind {dataset} 請求失敗: {e}"}

    if payload.get("status") != 200:
        return {"error": f"FinMind {dataset}: {payload.get('msg', '查無資料')}"}
    return {"dataset": dataset, "data_id": data_id, "data": payload.get("data", [])}


# ── 各 dataset 的具名 function（讓 Agent / import 端語意清楚）────────────

def fetch_per_pbr(data_id: str, start_date: str | None = None) -> dict:
    """本益比 PER / 淨值比 PBR / 殖利率（歷史序列）。"""
    return fetch_dataset("TaiwanStockPER", data_id, start_date or _default_start())


def fetch_price(data_id: str, start_date: str | None = None) -> dict:
    """日收盤價量。"""
    return fetch_dataset("TaiwanStockPrice", data_id, start_date or _default_start())


def fetch_month_revenue(data_id: str, start_date: str | None = None) -> dict:
    """月營收。"""
    return fetch_dataset("TaiwanStockMonthRevenue", data_id, start_date or _default_start(730))


def fetch_income_statement(data_id: str, start_date: str | None = None) -> dict:
    """綜合損益表。"""
    return fetch_dataset("TaiwanStockFinancialStatements", data_id, start_date or _default_start(730))


def fetch_balance_sheet(data_id: str, start_date: str | None = None) -> dict:
    """資產負債表。"""
    return fetch_dataset("TaiwanStockBalanceSheet", data_id, start_date or _default_start(730))


def fetch_cash_flow(data_id: str, start_date: str | None = None) -> dict:
    """現金流量表。"""
    return fetch_dataset("TaiwanStockCashFlowsStatement", data_id, start_date or _default_start(730))


def fetch_dividend(data_id: str, start_date: str | None = None) -> dict:
    """股利政策。"""
    return fetch_dataset("TaiwanStockDividend", data_id, start_date or _default_start(1825))


def fetch_institutional(data_id: str, start_date: str | None = None) -> dict:
    """三大法人買賣超。"""
    return fetch_dataset("TaiwanStockInstitutionalInvestorsBuySell", data_id, start_date or _default_start(90))


def fetch_margin(data_id: str, start_date: str | None = None) -> dict:
    """融資融券。"""
    return fetch_dataset("TaiwanStockMarginPurchaseShortSale", data_id, start_date or _default_start(90))


def fetch_shareholding(data_id: str, start_date: str | None = None) -> dict:
    """外資持股比率。"""
    return fetch_dataset("TaiwanStockShareholding", data_id, start_date or _default_start(90))


def fetch_info(data_id: str) -> dict:
    """基本資料（名稱、產業別、上市/上櫃）。"""
    return fetch_dataset("TaiwanStockInfo", data_id)


def fetch_news(data_id: str, start_date: str | None = None) -> dict:
    """相關新聞。"""
    return fetch_dataset("TaiwanStockNews", data_id, start_date or _default_start(30))


def fetch_tick_snapshot(data_id: str) -> dict:
    """即時 tick 快照（收盤/漲跌/量，單一端點 taiwan_stock_tick_snapshot）。

    與各 dataset 走不同端點（/taiwan_stock_tick_snapshot），回原始 payload。
    402/403 額度用盡時換下一個 token 重試一次。回 {"data":[...]} 或 {"error"}。
    """
    headers = {"Authorization": f"Bearer {_next_token()}"}
    params = {"data_id": data_id}
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT, verify=False) as client:
            r = client.get(FINMIND_TICK_SNAPSHOT_URL, headers=headers, params=params)
            if r.status_code in (402, 403):
                headers = {"Authorization": f"Bearer {_next_token()}"}
                r = client.get(FINMIND_TICK_SNAPSHOT_URL, headers=headers, params=params)
            if r.status_code != 200:
                # 400 + "level is free" = 此端點需 FinMind 付費方案，非程式錯誤。
                detail = ""
                try:
                    msg = r.json().get("msg", "")
                    if "level is free" in msg:
                        detail = "（此端點需 FinMind 付費方案；免費 token 無權限）"
                    elif msg:
                        detail = f"（{msg[:80]}）"
                except Exception:
                    pass
                return {"error": f"FinMind tick_snapshot HTTP {r.status_code}: {data_id}{detail}"}
            return r.json()
    except Exception as e:
        logger.debug("FinMind tick_snapshot error: %s", e)
        return {"error": f"FinMind tick_snapshot 請求失敗: {e}"}


def _parse_args(argv: list[str]) -> tuple[str, str, str | None]:
    mode = None
    symbol = None
    start = None
    for flag in _MODE_DATASET:
        if f"--{flag}" in argv:
            mode = flag
            idx = argv.index(f"--{flag}")
            if idx + 1 < len(argv):
                symbol = argv[idx + 1]
            break
    if "--start" in argv:
        try:
            start = argv[argv.index("--start") + 1]
        except IndexError:
            pass
    return mode, symbol, start


def _run(mode: str, symbol: str, start: str | None) -> dict:
    dataset = _MODE_DATASET[mode]
    if mode == "info":
        return fetch_info(symbol)
    # 各 dataset 有各自合理的預設起始，走 fetch_dataset 前先套 default
    dispatch = {
        "per": fetch_per_pbr, "price": fetch_price, "revenue": fetch_month_revenue,
        "income": fetch_income_statement, "balance": fetch_balance_sheet,
        "cashflow": fetch_cash_flow, "dividend": fetch_dividend,
        "institution": fetch_institutional, "margin": fetch_margin,
        "shareholding": fetch_shareholding, "news": fetch_news,
    }
    return dispatch[mode](symbol, start)


if __name__ == "__main__":
    args = sys.argv[1:]
    # snapshot 走不同端點（非 /data dataset），特判。
    if "--snapshot" in args:
        idx = args.index("--snapshot")
        sym = args[idx + 1] if idx + 1 < len(args) else None
        if not sym:
            print(json.dumps({"error": "用法: python tools/raw/finmind.py --snapshot SYMBOL"}, ensure_ascii=False))
            sys.exit(1)
        result = fetch_tick_snapshot(sym)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if isinstance(result, dict) and "error" in result else 0)

    mode, symbol, start = _parse_args(args)
    if not mode or not symbol:
        flags = "|".join(f"--{m}" for m in _MODE_DATASET)
        print(json.dumps({"error": f"用法: python tools/raw/finmind.py [{flags}|--snapshot] SYMBOL [--start YYYY-MM-DD]"},
                         ensure_ascii=False))
        sys.exit(1)

    result = _run(mode, symbol, start)
    print(json.dumps(result, ensure_ascii=False))
    if isinstance(result, dict) and "error" in result:
        sys.exit(1)
