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

    result = asyncio.run(analyze(symbol, prompt))
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
