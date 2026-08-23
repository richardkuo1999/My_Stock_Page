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
import math
import os
import sys
from datetime import datetime

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

# ── DCF 估值固定參數（一字不改搬自 uanalyze_cli/dcf_valuation_calculator.py）──
WACC = 0.12  # 折現率
TERMINAL_G = 0.03  # 永續成長率
REV_SENSITIVITY = 0.4  # 營收超越預期調節強度
LAMBDA_BASE = 0.50  # 衰減速度基礎值
LAMBDA_N_STEP = 0.12  # 每少一年 N 加快衰減的幅度
N_MAX_CONVERGE = 5  # 收斂時最大可信年數
N_MAX_DIVERGE = 3  # 發散時最大可信年數
# 來源 BASE_YEAR = datetime.now().year - 1 為模組全域常數（時間依賴，難測）；
# 這裡改成 _compute_dcf 的可注入參數（見下），公式本體不變。


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


# ── A5 時間加權動態 DCF 估值（only_dcf 純數字路徑；不呼叫 AI）───────────────


def _compute_dcf(
    eps_hist: dict,
    eps_fore: dict,
    rev_gap_pct_str: str,
    rev_gap_val: float,
    current_month: int = 8,
    base_year: int | None = None,
) -> tuple:
    """
    回傳 (base_ttm, v_2025, v_2026E, v_2027E, far_fore_yr, far_fore_eps,
          confidence_level, intrinsic_val)

    純數學函式（一字不改搬自 dcf_valuation_calculator.py 的 _compute_dcf）。
    唯一差異：來源用模組全域 BASE_YEAR = datetime.now().year - 1；這裡改成可注入
    的 base_year 參數（None 時退回相同的當下計算），公式本體不變、便於測試。
    """
    if base_year is None:
        base_year = datetime.now().year - 1
    BASE_YEAR = base_year

    sorted_fore_yrs = sorted(eps_fore.keys())
    v_2025 = eps_hist[max(eps_hist.keys())]
    v_2026E = eps_fore[sorted_fore_yrs[0]]
    v_2027E = eps_fore.get(BASE_YEAR + 2)  # 2027E

    # 營收超越/落後預期調節乘數
    rev_multiplier = math.exp(REV_SENSITIVITY * (rev_gap_val / 100.0)) if rev_gap_pct_str != "-" else 1.0

    # Base TTM（時間加權，受營收預期調節）
    w_hist = (12 - (current_month - 1)) / 12.0
    w_fore = (current_month - 1) / 12.0
    base_ttm = (w_hist * v_2025 + w_fore * v_2026E) * rev_multiplier

    # ── 法人預估年數 N 判定（完全信任法人數據，不設發散 N 上限截斷）────────
    far_fore_yr = sorted_fore_yrs[-1]
    n_known_years = max(1, far_fore_yr - BASE_YEAR)
    last_known_fore_yr = far_fore_yr
    last_known_eps = eps_fore[far_fore_yr]

    # ── 衰減起點成長率（邊際 YoY 與 CAGR 調和防暴衝）───────────────────────────
    prev_fore_eps = eps_fore.get(last_known_fore_yr - 1)
    if prev_fore_eps is not None and prev_fore_eps > 0 and last_known_eps > 0:
        marginal_yoy = (last_known_eps / prev_fore_eps) - 1.0
    elif last_known_eps > 0:
        cagr_base = max(1.0, base_ttm) if base_ttm > 0 else max(1.0, abs(v_2026E))
        marginal_yoy = (last_known_eps / cagr_base) - 1.0
    else:
        marginal_yoy = 0.0

    # 全期間同等 CAGR (從 Base TTM 到 last_known_fore_yr)
    if base_ttm > 0 and last_known_eps > 0 and n_known_years > 0:
        overall_cagr = (last_known_eps / base_ttm) ** (1.0 / n_known_years) - 1.0
    else:
        overall_cagr = marginal_yoy

    rev_multiplier = math.exp(REV_SENSITIVITY * (rev_gap_val / 100.0)) if rev_gap_pct_str != "-" else 1.0
    raw_marginal_g = max(0.0, marginal_yoy) * rev_multiplier
    raw_cagr_g = max(0.0, overall_cagr) * rev_multiplier

    # 衰減起點成長率取平滑調和值，並設定長線衰減天花板 (Cap at 50%)
    raw_decay_start_g = min(raw_marginal_g, max(raw_cagr_g, 0.50))
    raw_decay_start_g = min(raw_decay_start_g, 0.50)

    # ── N 門檻與衰減速度設定 ──────────────────────────────────────
    confidence_level = f"高 (法人完全直連 N={n_known_years})"
    decay_start_g = raw_decay_start_g
    lambda_decay = LAMBDA_BASE + LAMBDA_N_STEP * (3 - min(3, n_known_years))

    # 若單一年 YoY 暴增 (>50%)，自動加大衰減速度 lambda，加速收斂至永續 3%
    if marginal_yoy > 0.50:
        lambda_decay += max(0.0, (marginal_yoy - 0.50) * 0.50)

    if n_known_years <= 2:
        if raw_marginal_g > 0.50:
            # 短預估期 (N<=2) 且邊際年增率暴增 >50%
            # 實施信心度打折：設定上限 50% 並加快衰減速度
            decay_start_g = min(raw_marginal_g * 0.40, 0.50)
            confidence_level = "⚠️ 低 (N≤2極端外推打折)"
            lambda_decay = max(lambda_decay, 0.70)
        else:
            confidence_level = "中低 (N≤2)"

    # ── 10 年 DCF 折現 ───────────────────────────────────────
    current_eps = base_ttm
    pv_sum = 0.0
    for yr in range(1, 11):
        target_year = BASE_YEAR + yr
        if target_year in eps_fore and target_year <= last_known_fore_yr:
            # Phase 1：法人直連
            current_eps = eps_fore[target_year]
        else:
            # Phase 2：負指數衰減，不低於永續成長率
            t = target_year - last_known_fore_yr
            curr_g = TERMINAL_G + (decay_start_g - TERMINAL_G) * math.exp(-lambda_decay * t)
            curr_g = max(curr_g, TERMINAL_G)
            current_eps = current_eps * (1.0 + curr_g)
        pv_sum += current_eps / ((1.0 + WACC) ** yr)

    # Terminal Value
    tv_10 = (current_eps * (1.0 + TERMINAL_G)) / (WACC - TERMINAL_G)
    pv_tv = tv_10 / ((1.0 + WACC) ** 10)
    intrinsic_val = round(pv_sum + pv_tv, 2)

    return base_ttm, v_2025, v_2026E, v_2027E, far_fore_yr, eps_fore[far_fore_yr], confidence_level, intrinsic_val


async def _fetch_eps_consensus_dcf(symbol: str) -> tuple[dict, dict]:
    """DCF 專用 EPS 來源（gidp，GIDP token）。回 (eps_hist, eps_fore)。

    端點 EPSRevenueConsensusEstimate，取 data.data.ua50187_cp.Data（年份->EPS，
    帶 (f) 後綴的是 forecast）。與 fetch_eps_consensus 不同端點，勿混用。best-effort。
    """
    eps_hist: dict[int, float] = {}
    eps_fore: dict[int, float] = {}
    try:
        headers = _auth.gidp_headers()
        url = f"{GIDP_BASE_URL}/data_fetch/api/EPSRevenueConsensusEstimate/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"country": "TW"})
        if r.status_code == 200:
            eps_data = (
                (r.json().get("data") or {}).get("data", {}).get("ua50187_cp", {}).get("Data", {}) or {}
            )
            for k, v in eps_data.items():
                if isinstance(v, (int, float)):
                    clean_k = str(k).replace("(f)", "").strip()
                    if "(f)" in str(k):
                        eps_fore[int(clean_k)] = float(v)
                    else:
                        eps_hist[int(clean_k)] = float(v)
    except Exception as e:
        logger.warning("_fetch_eps_consensus_dcf failed for %s: %s", symbol, e)
    return eps_hist, eps_fore


async def _fetch_revenue_tracking_dcf(symbol: str) -> tuple[str, str, float]:
    """DCF 專用營收動能（gidp）。回 (rev_gap_pct_str, rev_trend_str, rev_gap_val)。

    端點 MonthlyRevenueTrackingConcensuslModule，取 data.data.ua70306_cp.Data
    （月份->百分比），最後一個月當 rev_gap_val。best-effort（失敗回預設）。
    """
    try:
        headers = _auth.gidp_headers()
        url = f"{GIDP_BASE_URL}/data_fetch/api/MonthlyRevenueTrackingConcensuslModule/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"country": "TW"})
        if r.status_code == 200:
            diff_data = (
                (r.json().get("data") or {}).get("data", {}).get("ua70306_cp", {}).get("Data", {})
            )
            if isinstance(diff_data, dict) and diff_data:
                m_keys = sorted(diff_data.keys())
                last_diff = diff_data[m_keys[-1]]
                if isinstance(last_diff, (int, float)):
                    rev_gap_val = float(last_diff)
                    rev_gap_pct_str = f"{last_diff:+.1f}%"
                    trend_parts = [
                        f"{m}月:{diff_data[m]:+.1f}%" if isinstance(diff_data[m], (int, float)) else f"{m}月:-"
                        for m in m_keys[-3:]
                    ]
                    return rev_gap_pct_str, " | ".join(trend_parts), rev_gap_val
    except Exception as e:
        logger.warning("_fetch_revenue_tracking_dcf failed for %s: %s", symbol, e)
    return "-", "-", 0.0


async def fetch_dcf_valuation(symbol: str) -> dict:
    """A5 時間加權動態 DCF 估值（純計算，不呼叫 AI）。

    ensure_token → asyncio.gather 並行抓 gidp EPS 共識 + 月營收動能 → EPS 不足回
    error → 否則跑 _compute_dcf + 1 年 roll-forward，回關鍵數字摘要 dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    (eps_hist, eps_fore), (rev_gap_pct_str, rev_trend_str, rev_gap_val) = await asyncio.gather(
        _fetch_eps_consensus_dcf(symbol),
        _fetch_revenue_tracking_dcf(symbol),
    )

    if not eps_hist or not eps_fore:
        return {"error": f"{symbol} EPS 資料不足，無法計算 DCF"}

    (
        base_ttm,
        v_2025,
        v_2026E,
        v_2027E,
        far_fore_yr,
        far_fore_eps,
        confidence_level,
        intrinsic_val,
    ) = _compute_dcf(eps_hist, eps_fore, rev_gap_pct_str, rev_gap_val)

    # 1-Year Roll-Forward DCF: V1 = V0 * (1 + WACC) - EPS_2026
    forward_val_1yr = round(intrinsic_val * (1.0 + WACC) - v_2026E, 2)

    return {
        "symbol": symbol,
        "每股合理內在價值": intrinsic_val,
        "1年後前瞻合理價值": forward_val_1yr,
        "當前時間加權基期": round(base_ttm, 2),
        "營收動能": rev_gap_pct_str,
        "2025實際獲利": round(v_2025, 2),
        "2026E": round(v_2026E, 2),
        "最遠預估年份及獲利": f"{far_fore_yr}E:{round(far_fore_eps, 2)}元",
        "信心度": confidence_level,
    }


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

    if args[0] == "--dcf":
        # A5 時間加權動態 DCF 估值摘要（Agent 用；純計算，不呼叫 AI）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --dcf <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_dcf_valuation(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    result = asyncio.run(analyze(symbol, prompt))
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
