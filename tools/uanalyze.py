"""uanalyze — UAnalyze AI 估值分析
用法: python tools/uanalyze.py SYMBOL [--prompt PROMPT]
     python tools/uanalyze.py --reports [--limit N]
回傳: JSON {"analysis": str}
   或 {"reports": [{id, stock_code, stock_name, title, date, summary}]}

認證：一次帳密登入（UAnalyzeAuth.login）後，可依 domain 取得三種認證材料：
  - jwt_headers():     data.uanalyze.twobitto.com / api.uanalyze.com.tw（Bearer <access_token>）
  - cookie_context():  cronjob.uanalyze.com.tw（記憶體 4-cookie + Origin/Referer，不吃 Bearer）
  - gidp_headers():    gidp.uanalyze.com.tw（前端寫死的固定 GIDP token，非登入產生）
這三個 helper 皆為純組裝（不發 HTTP、不呼叫 AI）。
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

AUTH_BASE_URL = os.getenv("UANALYZE_AUTH_URL", "https://api.uanalyze.com.tw")
BASE_URL = "https://data.uanalyze.twobitto.com"
# cronjob domain（cookie 認證，不吃 Bearer；供後續 ticket 用）。
CRONJOB_BASE_URL = "https://cronjob.uanalyze.com.tw"
# gidp domain（GIDP 固定 token 認證；供後續 ticket 用）。
GIDP_BASE_URL = "https://gidp.uanalyze.com.tw"
# UAnalyze 前端 JS 公開寫死的固定 GIDP token，非登入產生，也不吃 JWT。
GIDP_TOKEN = "tquEQGIZfck2lYDdBst9LBF5p6jfQepV"
DEFAULT_TIMEOUT = 60.0
DEFAULT_PROMPT = "近況發展"


class UAnalyzeAuth:
    """Manages JWT authentication for UAnalyze API."""

    def __init__(self):
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_type: str | None = None
        self.expires_in: int | None = None

    def _get_credentials(self) -> tuple[str, str]:
        email = os.getenv("UANALYZE_EMAIL", "").strip()
        password = os.getenv("UANALYZE_PASSWORD", "").strip()
        return email, password

    async def login(self) -> bool:
        """Login with email/password to get tokens."""
        email, password = self._get_credentials()
        if not email or not password:
            return False
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                r = await client.post(
                    f"{AUTH_BASE_URL}/auth/token",
                    json={"email": email, "password": password},
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json",
                        "Origin": "https://pro.uanalyze.com.tw",
                        "Referer": "https://pro.uanalyze.com.tw/",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    payload = data.get("data") if isinstance(data.get("data"), dict) else data
                    self.access_token = payload.get("access_token")
                    self.refresh_token = payload.get("refresh_token")
                    # cookie helper 需要完整 4 欄，一併存下。
                    self.token_type = payload.get("token_type")
                    self.expires_in = payload.get("expires_in")
                    return bool(self.access_token)
                logger.warning("UAnalyze login failed: HTTP %d", r.status_code)
                return False
        except Exception as e:
            logger.error("UAnalyze login error: %s", e)
            return False

    async def refresh(self) -> bool:
        """Refresh the access token."""
        if not self.refresh_token:
            return False
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                r = await client.post(
                    f"{AUTH_BASE_URL}/auth/token/refresh",
                    json={"refresh_token": self.refresh_token},
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json",
                        "Origin": "https://pro.uanalyze.com.tw",
                        "Referer": "https://pro.uanalyze.com.tw/",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    payload = data.get("data") if isinstance(data.get("data"), dict) else data
                    self.access_token = payload.get("access_token")
                    return bool(self.access_token)
                return False
        except Exception as e:
            logger.error("UAnalyze refresh error: %s", e)
            return False

    async def ensure_token(self) -> str | None:
        """Ensure we have a valid access token."""
        if self.access_token:
            return self.access_token
        if await self.login():
            return self.access_token
        return None

    # --- Per-domain auth material assembly (pure, no HTTP, no AI) ---
    # 假設已 login（access_token 已存在）。只組裝 request 材料，不發請求。

    def jwt_headers(self) -> dict:
        """A: JWT Bearer headers（data.uanalyze.twobitto.com / api.uanalyze.com.tw）。"""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://pro.uanalyze.com.tw/",
        }

    def cookie_context(self) -> tuple[dict, dict]:
        """B: cookie 認證材料（cronjob.uanalyze.com.tw）。

        回 (cookies, headers)。cronjob domain 不吃 Bearer header，需要記憶體組的
        完整 4-cookie 加上 Origin/Referer（缺其一實測 403）。
        """
        cookies = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type if self.token_type is not None else "",
            "expires_in": str(self.expires_in),
        }
        headers = {
            "Origin": "https://pro.uanalyze.com.tw",
            "Referer": "https://pro.uanalyze.com.tw/",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }
        return cookies, headers

    def gidp_headers(self) -> dict:
        """C: GIDP 認證材料（gidp.uanalyze.com.tw）。

        用前端寫死的固定 GIDP_TOKEN（非登入產生、也不吃 JWT），不是 access_token。
        """
        return {
            "Authorization": f"Bearer {GIDP_TOKEN}",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://pro.uanalyze.com.tw/",
        }


# Module-level auth instance (reused across calls)
_auth = UAnalyzeAuth()


async def _request_with_auth(url: str, params: dict | None = None) -> dict | None:
    """Make authenticated request, auto-refresh on 401."""
    token = await _auth.ensure_token()
    if not token:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://pro.uanalyze.com.tw/",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        r = await client.get(url, headers=headers, params=params)

        if r.status_code == 401:
            # Try refresh
            if await _auth.refresh():
                headers = {"Authorization": f"Bearer {_auth.access_token}"}
                r = await client.get(url, headers=headers, params=params)
            else:
                # Try full re-login
                if await _auth.login():
                    headers = {"Authorization": f"Bearer {_auth.access_token}"}
                    r = await client.get(url, headers=headers, params=params)
                else:
                    return None

        if r.status_code == 200:
            return r.json()
        return None


async def get_completion(symbol: str, prompt: str = DEFAULT_PROMPT) -> dict:
    """Get AI completion for a stock with a specific prompt."""
    url = f"{BASE_URL}/completions"
    params = {"prompt": prompt, "stock": symbol}
    result = await _request_with_auth(url, params)
    if result and "data" in result:
        text = (
            result["data"].get("text", "")
            if isinstance(result["data"], dict)
            else str(result["data"])
        )
        return {"analysis": text, "prompt": prompt, "symbol": symbol}
    return {"error": f"UAnalyze 無法取得 {symbol} 的分析結果"}


async def get_reports(symbol: str) -> dict:
    """Get report summaries for a stock."""
    url = f"{BASE_URL}/api/report-summaries"
    params = {"stock": symbol}
    result = await _request_with_auth(url, params)
    if result and "data" in result:
        reports = []
        for item in result["data"]:
            reports.append(
                {
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "date": item.get("date", ""),
                    "url": item.get("url", ""),
                }
            )
        return {"reports": reports, "symbol": symbol}
    return {"error": f"UAnalyze 無法取得 {symbol} 的報告"}


async def list_latest_reports(limit: int = 50) -> dict:
    """List the latest site-wide research reports (pure data, no AI, no push).

    Used by the scheduled monitor to detect newly published reports. Returns
    reports newest-first with the fields needed for dedup (id) and display.
    """
    url = f"{BASE_URL}/api/report-summaries"
    result = await _request_with_auth(url, {"limit": limit, "offset": 0})
    if not result or "data" not in result:
        return {"error": "UAnalyze 無法取得最新報告列表"}

    # Endpoint may return data:[...] or data:{data:[...]}.
    raw = result["data"]
    items = raw.get("data", []) if isinstance(raw, dict) else raw

    reports = []
    for item in items:
        reports.append(
            {
                "id": item.get("id"),
                # Real UAnalyze schema: name=股票代號, stock_name=公司名,
                # question_type=報告主題（當標題用；無獨立標題欄位）。
                "stock_code": item.get("name", ""),
                "stock_name": item.get("stock_name", ""),
                "title": item.get("question_type", "") or item.get("title", ""),
                "date": (item.get("content_date", "") or item.get("date", ""))[:10],
                "summary": item.get("summary", ""),
            }
        )
    return {"reports": reports}


async def analyze(symbol: str, prompt: str = DEFAULT_PROMPT) -> dict:
    """Main entry: analyze a stock via UAnalyze AI.

    Args:
        symbol: Stock symbol (e.g. '2330')
        prompt: Analysis prompt (default: '近況發展')

    Returns:
        dict with 'analysis' key on success, or 'error' key on failure
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}

    email = os.getenv("UANALYZE_EMAIL", "").strip()
    password = os.getenv("UANALYZE_PASSWORD", "").strip()
    if not email or not password:
        return {"error": "UANALYZE_EMAIL 或 UANALYZE_PASSWORD 未設定"}

    return await get_completion(symbol, prompt)


def _latest_periods(data_map: dict, n: int) -> list[tuple[str, float]]:
    """Sort a {period: value} dict by period key (ascending) and take the last n.

    Periods are strings like '2025Q3' or '07' — lexical sort matches chronology
    for these fixed-width formats. Returns [(period, value), ...] newest-last.
    """
    if not isinstance(data_map, dict) or not data_map:
        return []
    items = sorted(data_map.items(), key=lambda kv: kv[0])
    return items[-n:]


async def fetch_eps_consensus(symbol: str, recent: int = 4) -> dict:
    """A3 法人共識：單季 EPS 實際 vs 法人預估（cronjob）+ 月營收共識（gidp）。

    純資料函式（不呼叫 AI，用 async httpx）。兩段各自 best-effort：任一失敗/空
    不影響另一段。回摘要 dict（只取最新幾期），兩段都空回 error dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    result: dict = {"symbol": symbol}

    # --- 單季 EPS 追蹤（cronjob domain，cookie 認證）---
    eps_summary: dict = {}
    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/EPSTrackingActualVSForecastModule/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, cookies=cookies, headers=headers)
        if r.status_code == 200:
            rows = (r.json().get("data") or {}).get("data") or {}
            # rows is a dict keyed by uaXXXXX_cp; match by ChineseAccount label.
            for row in rows.values() if isinstance(rows, dict) else []:
                if not isinstance(row, dict):
                    continue
                label = row.get("ChineseAccount", "")
                data_map = row.get("Data", {})
                if "實際EPS" in label:
                    eps_summary["實際EPS"] = [
                        {"period": p, "value": v} for p, v in _latest_periods(data_map, recent)
                    ]
                elif "法人共識" in label:
                    eps_summary["法人共識預估EPS"] = [
                        {"period": p, "value": v} for p, v in _latest_periods(data_map, recent)
                    ]
    except Exception as e:
        logger.warning("fetch_eps_consensus EPS section failed for %s: %s", symbol, e)

    # --- 月營收共識（gidp domain，GIDP token）---
    rev_summary: dict = {}
    try:
        headers = _auth.gidp_headers()
        url = f"{GIDP_BASE_URL}/data_fetch/api/MonthlyRevenueTrackingConcensuslModule/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"country": "TW"})
        if r.status_code == 200:
            rows = (r.json().get("data") or {}).get("data") or {}
            for row in rows.values() if isinstance(rows, dict) else []:
                if not isinstance(row, dict):
                    continue
                label = row.get("ChineseAccount", "")
                data_map = row.get("Data", {})
                if "法人共識" in label:
                    rev_summary["法人共識估計月營收"] = [
                        {"month": p, "value": v} for p, v in _latest_periods(data_map, recent)
                    ]
                elif "累計今年月營收" in label:
                    rev_summary["累計今年月營收"] = [
                        {"month": p, "value": v} for p, v in _latest_periods(data_map, recent)
                    ]
                elif "超法人預期" in label:
                    rev_summary["累計營收超法人預期(%)"] = [
                        {"month": p, "value": v} for p, v in _latest_periods(data_map, recent)
                    ]
    except Exception as e:
        logger.warning("fetch_eps_consensus revenue section failed for %s: %s", symbol, e)

    if not eps_summary and not rev_summary:
        return {"error": f"查無 {symbol} 的法人共識資料"}

    if eps_summary:
        result["eps"] = eps_summary
    if rev_summary:
        result["revenue"] = rev_summary
    return result


async def fetch_per_share_metrics(symbol: str, years: int = 5) -> dict:
    """A4 財務指標：每股自由現金流/EPS/EBITDA/ROE/ROIC/股利等（cronjob）。

    純資料函式（不呼叫 AI，用 async httpx）。來源是多年份時間序列，每列一個
    指標（row_title_left）+ 各年份欄位（D2025...）。只取最新 `years` 年，回摘要。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/PerShareValueForValuationModel/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, cookies=cookies, headers=headers)
    except Exception as e:
        logger.warning("fetch_per_share_metrics failed for %s: %s", symbol, e)
        return {"error": f"查無 {symbol} 的財務指標資料"}

    if r.status_code != 200:
        return {"error": f"查無 {symbol} 的財務指標資料"}

    rows = (r.json().get("data") or {}).get("data") or []
    if not isinstance(rows, list) or not rows:
        return {"error": f"查無 {symbol} 的財務指標資料"}

    metrics: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("row_title_left", "")
        if not name:
            continue
        # Year columns look like 'D2025'; sort descending, take newest `years`.
        year_cols = sorted(
            (k for k in row if k.startswith("D") and k[1:].isdigit()),
            reverse=True,
        )[:years]
        values = {col[1:]: row[col] for col in year_cols}
        if values:
            metrics.append({"name": name, "values": values})

    if not metrics:
        return {"error": f"查無 {symbol} 的財務指標資料"}

    return {"symbol": symbol, "metrics": metrics}


async def fetch_supply_chain(symbol: str) -> dict:
    """A7 供應鏈：同業/供應鏈對照標的清單（cronjob）。

    純資料函式（不呼叫 AI，用 async httpx）。來源 data.data 是輕量的代號清單
    （實測 ['2303','5347','6770']，元素為純代號字串）。回 {'symbol','peers',...}，
    無資料回 error dict。防禦性處理 dict 形狀的元素（取其中的代號欄位）。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/StockComparisonStockPool/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, cookies=cookies, headers=headers)
    except Exception as e:
        logger.warning("fetch_supply_chain failed for %s: %s", symbol, e)
        return {"error": f"查無 {symbol} 的供應鏈資料"}

    if r.status_code != 200:
        return {"error": f"查無 {symbol} 的供應鏈資料"}

    data = (r.json().get("data") or {})
    raw = data.get("data") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        return {"error": f"查無 {symbol} 的供應鏈資料"}

    peers: list[str] = []
    for item in raw:
        if isinstance(item, str):
            code = item.strip()
        elif isinstance(item, dict):
            # 防禦：實測是純字串，但若日後回 dict，取常見代號欄位。
            code = str(
                item.get("stock_code")
                or item.get("code")
                or item.get("symbol")
                or item.get("name")
                or ""
            ).strip()
        else:
            code = str(item).strip()
        if code:
            peers.append(code)

    if not peers:
        return {"error": f"查無 {symbol} 的供應鏈資料"}

    result = {"symbol": symbol, "peers": peers}
    # 若來源附帶自身公司名，一併回傳供顯示（best-effort）。
    if isinstance(data, dict) and data.get("stock_name"):
        result["stock_name"] = data["stock_name"]
    return result


def _order_rows(payload: dict) -> dict:
    """Extract the non-empty inner data of an order/contract module response.

    回應形狀為 {'data': {'data': <list|dict|None>, 'country':...}}。稀疏時
    data.data 為 None/空。回非空的 data.data，否則回 {}。
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    inner = data.get("data") if isinstance(data, dict) else None
    if isinstance(inner, (list, dict)) and inner:
        return {"inner": inner}
    return {}


async def fetch_order_visibility(symbol: str) -> dict:
    """A8 訂單能見度：訂單能見度 + 合約負債（cronjob，資料稀疏）。

    純資料函式（不呼叫 AI，用 async httpx）。兩個端點各 best-effort。實測多數
    個股（含 2330）兩端皆回空 data.data（僅 {'country':'TW'}）→ 兩者都空時回
    error dict，讓 bot 回清楚的「查無」提示；有任一端有資料才回摘要 dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    result: dict = {"symbol": symbol}

    # --- 訂單能見度 ---
    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/OrderVisibilityModule/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, cookies=cookies, headers=headers)
        if r.status_code == 200:
            rows = _order_rows(r.json())
            if rows:
                result["order_visibility"] = rows["inner"]
    except Exception as e:
        logger.warning("fetch_order_visibility (order) failed for %s: %s", symbol, e)

    # --- 合約負債 ---
    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/ContractLiabilityModule/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, cookies=cookies, headers=headers)
        if r.status_code == 200:
            rows = _order_rows(r.json())
            if rows:
                result["contract_liability"] = rows["inner"]
    except Exception as e:
        logger.warning("fetch_order_visibility (contract) failed for %s: %s", symbol, e)

    if "order_visibility" not in result and "contract_liability" not in result:
        return {"error": f"查無 {symbol} 的訂單能見度資料"}
    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(
            json.dumps(
                {"error": "用法: python tools/uanalyze.py SYMBOL [--prompt PROMPT]"},
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    symbol = args[0]
    prompt = DEFAULT_PROMPT
    if "--prompt" in args:
        try:
            prompt = args[args.index("--prompt") + 1]
        except IndexError:
            pass

    if args[0] == "--reports":
        # List latest site-wide reports (monitor feed), no symbol needed.
        limit = 50
        if "--limit" in args:
            try:
                limit = int(args[args.index("--limit") + 1])
            except (IndexError, ValueError):
                pass
        result = asyncio.run(list_latest_reports(limit))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--consensus":
        # A3 法人共識摘要（Agent 用）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --consensus <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_eps_consensus(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--pershare":
        # A4 財務指標摘要（Agent 用）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --pershare <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_per_share_metrics(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--supply":
        # A7 供應鏈/同業清單摘要（Agent 用）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --supply <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_supply_chain(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--order":
        # A8 訂單能見度/合約負債摘要（Agent 用；資料稀疏可能無資料）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --order <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_order_visibility(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    result = asyncio.run(analyze(symbol, prompt))
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
