"""uanalyze — UAnalyze AI 估值分析 + 純數據查詢
用法（AI 分析）:
     python tools/uanalyze.py SYMBOL [--prompt PROMPT]        # 單一面向 AI 分析
     python tools/uanalyze.py --multi SYMBOL --prompts a,b,c [--concurrency N]  # 並行多面向
用法（純數據，不呼叫 AI）:
     python tools/uanalyze.py --reports [--limit N]           # 全站最新研究報告清單
     python tools/uanalyze.py --consensus SYMBOL              # 法人共識（單季 EPS + 月營收）
     python tools/uanalyze.py --pershare SYMBOL               # 每股財務指標（FCF/EPS/ROE/ROIC…）
     python tools/uanalyze.py --supply SYMBOL                 # 同業／供應鏈對照標的清單
     python tools/uanalyze.py --order SYMBOL                  # 訂單能見度 + 合約負債（市場排行表取數）
     python tools/uanalyze.py --fundamentals SYMBOL           # 即時基本面（收盤/漲跌/本益比…；無資料回 {}）
     python tools/uanalyze.py --dcf SYMBOL                    # 時間加權動態 DCF 估值（純計算）
     python tools/uanalyze.py --valuation SYMBOL             # 相對估值 PE/PB Band（長歷史+同業中位數+現值百分位）
     python tools/uanalyze.py --chips SYMBOL                 # 三大法人買賣超（近20日明細 + 合計，單位張）
     python tools/uanalyze.py --margins SYMBOL               # 三率趨勢（毛利率/營業利益率/稅後淨利率，近8季）
     python tools/uanalyze.py --cashflow SYMBOL              # 現金流趨勢（營業/投資/籌資/自由現金流，近8季）
     python tools/uanalyze.py --dividend SYMBOL              # 股利政策（現金股息 + 發放率，近10年）
     python tools/uanalyze.py --peers-compare SYMBOL         # 同業多維比較（本檔+同業 PE/PB/三率對照表）
     python tools/uanalyze.py --margin SYMBOL                # 信用交易（融資餘額/使用率 + 融券餘額/使用率，近10日）
     python tools/uanalyze.py --holders SYMBOL               # 籌碼結構（外資/董監持股比率 + 股東人數/大戶比率，近6期）
     python tools/uanalyze.py --transcript SYMBOL [id 或 date]  # 法說會逐字稿（無 selector 列清單，有則回全文）
     python tools/uanalyze.py --ask SYMBOL "問題" [general|knowledge|teacher]  # AI 知識庫問答（串流收集成完整答案）
     python tools/uanalyze.py --radar 關鍵字 [types]         # 批次雷達（多類全站資料，落地成檔回路徑+摘要；可數十MB）
     python tools/uanalyze.py --smart-estimate SYMBOL       # 前瞻共識：法人預估EPS/營收/毛利率/淨利/資本支出/股息（平均/最低/最高，年度）
     python tools/uanalyze.py --forecast-route SYMBOL       # 前瞻共識：未來五季營收/EPS/毛利率/營益率預估路徑 + 分析師評等佔比趨勢
回傳: 一律 JSON。
   預設:         {"analysis": str, "prompt", "symbol"}
   --multi:      {"symbol","requested","ok","failed","results":{面向: {analysis|error}}}
   --reports:    {"reports": [{id, stock_code, stock_name, title, date, summary}]}
   --consensus:  {"symbol","eps":{…},"revenue":{…},"annual":[…],"broker_eps":[…]}
   --pershare:   {"symbol","metrics":[{name, values:{年份: 值}}]}
   --supply:     {"symbol","peers":[代號…]}
   --order:      {"symbol","stock_name"?,"order_visibility"?,"contract_liability"?}
   --dcf:        {"symbol","每股合理內在價值","1年後前瞻合理價值","信心度",…}
   --valuation:  {"symbol","stock_name"?,"pe":{latest,avg_10y,std_bands,percentile_in_history,peer_median},"pb":{…}}
   --chips:      {"symbol","unit":"張","recent_days":[{date,外資,投信,自營商,合計}],"sum_recent":{…}}
   --margins:    {"symbol","unit":"%","margins":{毛利率:[{period,value}],營業利益率:[…],稅後淨利率:[…]},"latest":{…}}
   --cashflow:   {"symbol","unit":"千元","flows":{營業活動現金流:[{period,value}],投資…,籌資…,自由現金流:[…]},"latest":{…}}
   --dividend:   {"symbol","dividends":[{year,現金股息,發放率(%)}],"latest":{…}}
   --peers-compare: {"symbol","peers_compared":[代號…],"rows":[{stock,本益比,股價淨值比,毛利率,營業利益率,稅後淨利率}]}
   --margin:     {"symbol","recent_days":[{date,融資餘額,融資使用率(%),融券餘額,融券使用率(%)}],"latest":{…}}
   --holders:    {"symbol","holdings":[{period,外資持股比率,董監持股比率,…}],"shareholders":[{period,總股東人數(人),…}],"latest":{…}}
   --transcript: 清單 {"symbol","transcripts":[{date,id}]} 或全文 {id,title,date,stock,字數,transcript}
   --ask:        {"symbol","question","knowledge_base","answer"}
   --radar:      {"keyword","types","file","bytes","summary":{類別: 筆數}}（內容寫檔，不整包回傳）
   --smart-estimate: {"symbol","unit_note","estimates":{"EPS":[{year,平均,最低,最高}],"營收":[…],…}}
   --forecast-route: {"symbol","route":{"未來五季EPS預估路徑":[{period,value}],…},"rating_trend":[{month,樂觀,中立,悲觀,收盤價}]}
   查無資料/失敗一律回 {"error": str}（--fundamentals 例外，best-effort 回 {}）。

面向清單（--prompt / --multi 用）見 UA_PROMPTS（DEFAULT_PROMPT 之後）。--multi 由
呼叫端自行選面向並以逗號傳入，內部並行跑（預設同時 4 個），單一面向失敗不影響其他。

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
import re
import sys
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

AUTH_BASE_URL = os.getenv("UANALYZE_AUTH_URL", "https://api.uanalyze.com.tw")
BASE_URL = "https://data.uanalyze.twobitto.com"
# data.uanalyze.com.tw：AI 問答串流（chat）、報告摘要等 JWT 端點（與 twobitto 網域並存）。
DATA_API_BASE = "https://data.uanalyze.com.tw/api"
# cronjob domain（cookie 認證，不吃 Bearer；供後續 ticket 用）。
CRONJOB_BASE_URL = "https://cronjob.uanalyze.com.tw"
# gidp domain（GIDP 固定 token 認證；供後續 ticket 用）。
GIDP_BASE_URL = "https://gidp.uanalyze.com.tw"
# UAnalyze 前端 JS 公開寫死的固定 GIDP token，非登入產生，也不吃 JWT。
GIDP_TOKEN = "tquEQGIZfck2lYDdBst9LBF5p6jfQepV"
DEFAULT_TIMEOUT = 120.0  # 2 分鐘 — /ua 分析/逐字稿可能較慢，放寬上限
DEFAULT_PROMPT = "近況發展"

# AI 問答知識庫（chat 端點）。短別名 → 完整 api_name；供 CLI/Agent 選擇。
UA_KNOWLEDGE_BASES: dict[str, str] = {
    "general": "ua_ai_insight_general",      # 一般問答（預設）
    "knowledge": "ua_ai_insight_knowledge",  # 個股深度分析
    "teacher": "ua_ai_insight_teacher",      # 投資教學
}
DEFAULT_KB = "general"

# company_keywords 批次雷達預設抓的資料類別。
DEFAULT_RADAR_TYPES = "company_info,ai_chat,transcript"

# UAnalyze 分析面向清單。每項為 (按鈕標籤, 實際送出的完整 prompt)。
# 標籤短、供 inline 按鈕；送出時用完整 prompt。取自 old_file 的 PROMPT_LIST（全保留）。
# 放在工具層作為單一來源：bot/handlers.py 的 /ua 選單由此 re-export，
# CLI/Agent 也能藉此得知有哪些現成面向可用。純文字常數，不呼叫 AI。
UA_PROMPTS: list[tuple[str, str]] = [
    ("近況發展", "近況發展"),
    ("產業趨勢", "產業趨勢"),
    ("產品線分析", "產品線分析"),
    ("長短期展望", "長短期展望"),
    ("供需分析", "供需分析"),
    ("觀察重點", "觀察重點"),
    ("利多因素", "利多因素"),
    ("利空因素", "利空因素"),
    ("接單狀況", "接單狀況"),
    ("資本支出", "資本支出"),
    ("新產品", "新產品"),
    ("時間表", "時間表"),
    ("相關公司", "相關公司"),
    ("同業競爭", "同業競爭"),
    ("護城河分析", "護城河分析"),
    ("併購分析", "併購分析"),
    ("重要數字", "重要數字"),
    ("公司概覽", "公司概覽"),
    ("銷售地區", "銷售地區"),
    ("描述庫存", "描述庫存"),
    (
        "營收成長來源",
        "驅動銷售金額(營收)成長或衰退的來源有哪些，詳細且完整的敍述原因(敍述時請用數據佐證你的論點(若有數據的話))，分為短期(意為持續性不強)、長期(意為持續不斷的動能)",
    ),
    (
        "獲利成長因子",
        "驅動獲利(盈餘)成長或衰退的因子有哪些，詳細且完整的敍述原因(敍述時請用數據佐證你的論點(若有數據的話))，分為短期(意為持續性不強)、長期(意為持續不斷的動能)",
    ),
    (
        "毛利率變化",
        "驅動毛利率(成本)上升或下降的因素有哪些，詳細且完整的敍述原因，可以的話用數據佐證你的論點，分為短期長期。如果資料不足允許提供較少內容，如果資料中找不到原因可以不提供。備註，業外不會影響毛利率，ASP與毛利率不一定相關",
    ),
    (
        "營收時間線",
        "根據資料，將有提到(營收)或(銷售)的資訊取出，重新改寫(改寫程度大)，理為時間線(依時間排序)(去除相同內容)(排除匯兌收益、EPS、毛利率相關資訊)",
    ),
    (
        "展望上下修",
        "法人或公司有展望上下修原因是什麼?請注意要有明確看法變化|調整的意思才算。以多層結構顯示，第1層先[[展望上修(正向調整)]]再<<展望下修(負向調整)>>，第2層 - 時間(例如2025年第一季)、 - 第3層類型(例如<<毛利率下修>>、[[出貨量上修]]以及其他類型)。注意，有上下修的才算，維持不變的不用顯示。如果沒有上下修相關資料，請回答『無相關資料』",
    ),
    (
        "關稅/生產基地",
        "請你幫我做2件事，第一、我提供的資料中是否有提到關稅、貿易戰、或相關細節內容(這很重要一定要找出來)...； 第二、提供公司的生產基地、工廠地點、據點的相關細節內容...",
    ),
    (
        "供應鏈重組",
        "請檢查提供的資料中是否有提到『供應鏈如何重組』、『美國製造基地資訊』、『關稅影響利潤及價格上漲議題』或者『對等關稅影響』的相關內容...如果回答時有相似內容請將其整合為一句，儘量提供具體數據以及具體案例來輔助說明...",
    ),
    (
        "匯率影響",
        "台幣兌美元升貶值對公司成本或競爭力(產業競爭程度如何)的影響(再分為升值 and 貶值)公司說明(如果有的話)及分析並綜合評估影響明顯程度，台幣兌美元升貶值對匯兌損益影響...。輸出：台幣升值情境分析：... 台幣貶值情境分析：...。記得標示正面和負面標記",
    ),
    (
        "AI 相關",
        "請檢查我提供的資料中是否有提到『AI』『邊緣AI』『人工智慧』『人工智能』或相關內容...如果回答時有相似內容請將其整合為一句，可以提供具體數據以及具體案例來輔助說明...",
    ),
    ("新產品進度", "有新產品嗎，進度如何，最後條列出新產品詳細數字"),
    (
        "資本支出細節",
        "詳述資本支出或擴產計劃，包含前因後果、項目、產能、金額、時間點、地點，若無資本支出或擴產，請回答『無資本支出相關資料』",
    ),
    (
        "庫存循環",
        "描述該公司的庫存情形，並在每一段敘述之後標註資料來源日期。我想更加了解該公司自身的庫存水位以及終端需求或客戶的庫存水位，接著想利用公司的接單情況來預判未來庫存循環方向",
    ),
]

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


# 併發預設值：實測 UAnalyze 對同時 4 個面向容忍良好且不被擋（見探測）。
DEFAULT_MULTI_CONCURRENCY = 4


async def analyze_multi(
    symbol: str,
    prompts: list[str],
    concurrency: int = DEFAULT_MULTI_CONCURRENCY,
) -> dict:
    """一次「並行」跑多個分析面向，共用同一登入 token。

    面向由呼叫端（Agent）自行決定並傳入——本工具不寫死面向清單。內部用
    asyncio.gather + Semaphore 分批並行（預設同時 4 個），避免一次轟炸 UAnalyze
    後端。單一面向失敗（無資料 / 逾時）只在該面向記為 error，不影響其他面向。

    Args:
        symbol: 股票代號（如 '4906'）。
        prompts: 要分析的面向清單（如 ['近況發展','產品線分析','利多因素']）。
        concurrency: 同時並行的面向數上限。

    Returns:
        {
          "symbol": "4906",
          "results": {"近況發展": {"analysis": "..."}, "產品線分析": {"error": "..."}, ...},
          "requested": [...], "ok": [...], "failed": [...]
        }
        或整體性錯誤時回 {"error": "..."}。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not prompts:
        return {"error": "請提供至少一個分析面向（--prompts a,b,c）"}

    email = os.getenv("UANALYZE_EMAIL", "").strip()
    password = os.getenv("UANALYZE_PASSWORD", "").strip()
    if not email or not password:
        return {"error": "UANALYZE_EMAIL 或 UANALYZE_PASSWORD 未設定"}

    # 去重但保留順序（Agent 可能重複帶入）。
    seen: set[str] = set()
    ordered = [p for p in (x.strip() for x in prompts) if p and not (p in seen or seen.add(p))]

    # 先確保已登入一次，讓併發請求共用 token（避免 N 個請求各觸發登入）。
    await _auth.ensure_token()

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(p: str) -> tuple[str, dict]:
        async with sem:
            try:
                return p, await get_completion(symbol, p)
            except Exception as e:  # noqa: BLE001 — 單顆失敗隔離，不拖垮整批
                logger.warning("面向 %s 分析失敗：%s", p, e)
                return p, {"error": f"面向 {p} 分析失敗：{e}"}

    pairs = await asyncio.gather(*[_one(p) for p in ordered])

    results = {p: r for p, r in pairs}
    ok = [p for p, r in pairs if "analysis" in r]
    failed = [p for p, r in pairs if "analysis" not in r]
    return {
        "symbol": symbol,
        "requested": ordered,
        "ok": ok,
        "failed": failed,
        "results": results,
    }


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
    """A3 法人共識：單季 EPS + 月營收 + 年度預估共識 + 各券商 EPS 明細。

    純資料函式（不呼叫 AI，用 async httpx）。四段各自 best-effort：任一失敗/空
    不影響其他段。回摘要 dict：
      eps        單季 EPS 實際 vs 法人預估（cronjob）
      revenue    月營收共識/達成率（gidp）
      annual     年度預估共識對照（gidp；每年 營收/EPS/本業EPS）
      broker_eps 法人最新 EPS 明細（gidp；近 90 天，以發布日期區分，逐年 2026E~2030E）
    四段全空回 error dict。
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

    # --- 年度預估共識對照表（gidp，GIDP token）---
    # C 表：法人對「每一年」的營收/EPS/本業EPS 預估（歷史+未來年度並排）。
    # 端點 EPSRevenueConsensusEstimate 三欄：ua50189_cp=營收、ua50187_cp=EPS、
    # ua50209_cp=本業EPS。與 --dcf 內部同端點，但這裡三欄都取、按年份組表。
    annual_rows: list[dict] = []
    try:
        headers = _auth.gidp_headers()
        url = f"{GIDP_BASE_URL}/data_fetch/api/EPSRevenueConsensusEstimate/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"country": "TW"})
        if r.status_code == 200:
            raw = (r.json().get("data") or {}).get("data") or {}
            rev_y = (raw.get("ua50189_cp") or {}).get("Data") or {}
            eps_y = (raw.get("ua50187_cp") or {}).get("Data") or {}
            core_y = (raw.get("ua50209_cp") or {}).get("Data") or {}
            # 年份鍵可能帶 (f) forecast 後綴，統一去掉再排序（保留原標記於 is_forecast）。
            years: list[str] = []
            for d in (rev_y, eps_y, core_y):
                if isinstance(d, dict):
                    for y in d.keys():
                        if y not in years:
                            years.append(y)
            for y in sorted(years, key=lambda s: str(s).replace("(f)", "").strip()):
                annual_rows.append({
                    "year": str(y).replace("(f)", "").strip(),
                    "is_forecast": "(f)" in str(y),
                    "營收": rev_y.get(y),
                    "EPS": eps_y.get(y),
                    "本業EPS": core_y.get(y),
                })
    except Exception as e:
        logger.warning("fetch_eps_consensus annual section failed for %s: %s", symbol, e)

    # --- 各家法人 EPS 明細（gidp，GIDP token）---
    # D 表：法人最新發布的逐年（2026E~2030E）預估 EPS。端點 EPSFilterTableE0001
    # 回「全市場」以發布日期為鍵，需以 stock_code 過濾本檔；只取近 broker_days 天。
    # 註：此端點無「發布券商/分析師名」欄位（只有 stock_name），故各筆以「發布日期」
    # 區分——同股不同日期即不同一份法人預估。
    broker_rows: list[dict] = []
    try:
        headers = _auth.gidp_headers()
        url = f"{GIDP_BASE_URL}/data_fetch/api/EPSFilterTableE0001"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"country": "TW"})
        if r.status_code == 200:
            data_dict = (r.json().get("data") or {}).get("data") or {}
            today = datetime.now()
            broker_days = 90  # 只取近 90 天內發布的預估（過期的剔除）
            for date_key, items in (data_dict.items() if isinstance(data_dict, dict) else []):
                if not isinstance(items, list):
                    continue
                try:
                    if (today - datetime.strptime(date_key, "%Y%m%d")).days > broker_days:
                        continue
                except ValueError:
                    pass
                for item in items:
                    if not isinstance(item, dict) or str(item.get("stock_code")) != symbol:
                        continue
                    fmt_date = (
                        f"{date_key[:4]}/{date_key[4:6]}/{date_key[6:]}"
                        if len(date_key) == 8 else date_key
                    )

                    def _eps(field: str) -> str:
                        raw_v = str(item.get(field, "") or "").split(",")[0].strip()
                        return raw_v if raw_v else "-"

                    broker_rows.append({
                        "date": fmt_date,
                        "2026E": _eps("uae10193_cp"),
                        "2027E": _eps("uae10194_cp"),
                        "2028E": _eps("uae10195_cp"),
                        "2029E": _eps("uae10196_cp"),
                        "2030E": _eps("uae10197_cp"),
                    })
            broker_rows.sort(key=lambda x: x["date"], reverse=True)
    except Exception as e:
        logger.warning("fetch_eps_consensus broker section failed for %s: %s", symbol, e)

    if not eps_summary and not rev_summary and not annual_rows and not broker_rows:
        return {"error": f"查無 {symbol} 的法人共識資料"}

    if eps_summary:
        result["eps"] = eps_summary
    if rev_summary:
        result["revenue"] = rev_summary
    if annual_rows:
        result["annual"] = annual_rows
    if broker_rows:
        result["broker_eps"] = broker_rows
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
    """Deprecated shape helper kept for backward compat (unused by A8 now).

    早期 A8 曾打 per-stock 的 OrderVisibilityModule/ContractLiabilityModule，
    回應形狀為 {'data': {'data': <list|dict|None>}}。那兩個端點現已被伺服器
    清空（回 {'country':'TW'}），A8 改走市場排行表（見 fetch_order_visibility）。
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    inner = data.get("data") if isinstance(data, dict) else None
    if isinstance(inner, (list, dict)) and inner:
        return {"inner": inner}
    return {}


# A8 訂單能見度：欄位分組（把排行表的欄位拆成「訂單能見度」與「合約負債」兩段）。
# 以 column_title 解碼後的「中文標籤」分組；未列到的欄位一律歸「訂單能見度」段。
_CONTRACT_LIABILITY_LABELS = {"合約負債佔營收幾%", "季合約負債季增率"}


async def fetch_order_visibility(symbol: str) -> dict:
    """A8 訂單能見度 + 合約負債（市場排行表 OrderVisibilitySingleRankings）。

    純資料函式（不呼叫 AI，用 async httpx）。

    來源改用 gidp `OrderVisibilitySingleRankings`（全市場排行表，~1900+ 檔），
    回應含 `data.data`（每列一檔，欄位為 uaXXXXX_cp 代碼）與 `data.column_title`
    （代碼→中文標籤對照，如 ua60255_cp→「合約負債佔營收幾%」）。本函式在表中以
    stock_code 過濾出該檔，用 column_title 解碼欄位，再依標籤拆成兩段：
      order_visibility  訂單能見度相關（季報公佈日/細產業/月營收年增率/存貨…）
      contract_liability 合約負債相關（合約負債佔營收幾%/季合約負債季增率）
    查無該檔回 error dict。

    註：舊的 per-stock 端點 OrderVisibilityModule/ContractLiabilityModule 已被
    伺服器清空（僅回 {'country':'TW'}），故改走這張排行表取數。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    try:
        headers = _auth.gidp_headers()
        url = f"{GIDP_BASE_URL}/data_fetch/api/OrderVisibilitySingleRankings"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"country": "TW"})
    except Exception as e:
        logger.warning("fetch_order_visibility failed for %s: %s", symbol, e)
        return {"error": f"查無 {symbol} 的訂單能見度資料"}

    if r.status_code != 200:
        return {"error": f"查無 {symbol} 的訂單能見度資料"}

    data = (r.json().get("data") or {}) if isinstance(r.json(), dict) else {}
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return {"error": f"查無 {symbol} 的訂單能見度資料"}

    # column_title 是 [{code: 中文標籤}, ...]，攤平成 {code: 中文標籤}。
    code_to_label: dict = {}
    for item in data.get("column_title") or []:
        if isinstance(item, dict):
            code_to_label.update(item)

    row = None
    for item in rows:
        if isinstance(item, dict) and str(item.get("stock_code")) == symbol:
            row = item
            break
    if row is None:
        return {"error": f"查無 {symbol} 的訂單能見度資料"}

    # 依 column_title 解碼欄位（保序），再分兩段；名稱/代號欄不進表。
    order_visibility: dict = {}
    contract_liability: dict = {}
    skip_codes = {"stock_title", "stock_code", "stock_name"}
    for code, value in row.items():
        if code in skip_codes:
            continue
        label = code_to_label.get(code, code)
        if label in _CONTRACT_LIABILITY_LABELS:
            contract_liability[label] = value
        else:
            order_visibility[label] = value

    result: dict = {"symbol": symbol}
    if row.get("stock_name"):
        result["stock_name"] = row["stock_name"]
    if order_visibility:
        result["order_visibility"] = order_visibility
    if contract_liability:
        result["contract_liability"] = contract_liability

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


# ── A9 即時基本面（附加在 /p，best-effort，純資料不呼叫 AI）───────────────


# WebStockInfo（gidp）實測回傳的 ChineseAccount → 我們挑用的基本面欄位。
# 實打 WebStockInfo/2330?country=TW 看到 12 個欄位，本益比/殖利率不在其中，
# 故本益比另從同 domain（gidp）的 HistoricalPer 月序列補（取最新一個月）。
_WEBSTOCKINFO_FIELDS = {
    "收盤價": "收盤價",
    "當日漲跌幅": "當日漲跌幅(%)",
    "最新財報": "最新財報",
    "月營收": "最新月營收",
    "掛牌類別": "掛牌類別",
}


async def fetch_stock_fundamentals(symbol: str) -> dict:
    """A9 即時基本面（附加在 /p 用）。純資料，不呼叫 AI，async httpx，gidp 認證。

    best-effort 附加物：任何失敗/逾時/無憑證都回 {}（**不是** error dict），
    因為呼叫端（/p）拿到價量就一定要回，基本面只是加分。

    來源：
    - gidp `WebStockInfo/{symbol}?country=TW`：實打回收盤價/當日漲跌幅/最新財報/
      月營收/掛牌類別/股本/股票分類等（key 為 uaXXXXX_cp，各帶 ChineseAccount+Data）。
    - gidp `HistoricalPer/{symbol}?country=TW`：本益比月序列（WebStockInfo 沒有本益比），
      取最新一個月。此段獨立 best-effort，失敗不影響 WebStockInfo 那段。

    Returns:
        摘要 dict（如 {'收盤價': 2410.0, '本益比': 27.9, ...}）；無資料/失敗回 {}。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {}

    summary: dict = {}

    # --- WebStockInfo（gidp）：基本市況欄位 ---
    try:
        headers = _auth.gidp_headers()
        url = f"{GIDP_BASE_URL}/data_fetch/api/WebStockInfo/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"country": "TW"})
        if r.status_code == 200:
            rows = (r.json().get("data") or {}).get("data") or {}
            if isinstance(rows, dict):
                for row in rows.values():
                    if not isinstance(row, dict):
                        continue
                    label = row.get("ChineseAccount", "")
                    if label in _WEBSTOCKINFO_FIELDS:
                        value = row.get("Data")
                        # 只收原子值（純數字/字串），跳過 list/dict 型欄位（如逐字稿/分類）。
                        if isinstance(value, (int, float, str)) and value not in ("", None):
                            summary[_WEBSTOCKINFO_FIELDS[label]] = value
    except Exception as e:
        logger.warning("fetch_stock_fundamentals WebStockInfo failed for %s: %s", symbol, e)

    # --- HistoricalPer（gidp）：本益比（WebStockInfo 未含），取最新一個月 ---
    try:
        headers = _auth.gidp_headers()
        url = f"{GIDP_BASE_URL}/data_fetch/api/HistoricalPer/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"country": "TW"})
        if r.status_code == 200:
            rows = (r.json().get("data") or {}).get("data") or {}
            if isinstance(rows, dict):
                for row in rows.values():
                    if not isinstance(row, dict):
                        continue
                    if "本益比" in row.get("ChineseAccount", ""):
                        latest = _latest_periods(row.get("Data", {}), 1)
                        if latest:
                            summary["本益比"] = latest[-1][1]
                        break
    except Exception as e:
        logger.warning("fetch_stock_fundamentals HistoricalPer failed for %s: %s", symbol, e)

    return summary


# ── A10 相對估值 PE/PB Band（cronjob，cookie 認證；純資料不呼叫 AI）───────────
# 補 finmind 版（日頻/近1年/自算SD）拿不到的三個維度：
#   1. 長歷史月序列（~20 年）+ 平台預算好的 10 年平均 ±1/2 標準差帶（refline）
#   2. 同產業本益比中位數（PE_Band 的 refdata，非主序列）
#   3. 現值在自身歷史的百分位（本函式自算）
# 端點（皆 cronjob，帶股票代碼）：
#   HistoricalPer/{symbol}   本益比月序列 + refline(10年均/±1/2SD)
#   HistoricalPbr/{symbol}   股價淨值比月序列 + refline
#   PE_Band/{symbol}         refdata 內含「同產業本益比中位數」


def _parse_ratio_series(payload: dict, label_kw: str) -> dict:
    """從 data.data 取出 ChineseAccount 含 label_kw 那列的 {月份: 值}（濾空）。"""
    rows = (payload.get("data") or {}).get("data") or {}
    if not isinstance(rows, dict):
        return {}
    for row in rows.values():
        if not isinstance(row, dict):
            continue
        if label_kw in row.get("ChineseAccount", ""):
            data = row.get("Data", {})
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, (int, float))}
    return {}


def _parse_refline(payload: dict) -> dict:
    """把 data.refline 攤平成 {中文標籤: 值}（10年平均 / ±標準差帶）。"""
    ref = (payload.get("data") or {}).get("refline") or {}
    out: dict = {}
    if isinstance(ref, dict):
        for row in ref.values():
            if isinstance(row, dict) and isinstance(row.get("Data"), (int, float)):
                out[row.get("ChineseAccount", "")] = row["Data"]
    return out


def _percentile_rank(series: dict, value: float | None) -> float | None:
    """value 在歷史序列中的百分位（0-100）；無值回 None。"""
    if value is None or not series:
        return None
    vals = [v for v in series.values() if isinstance(v, (int, float))]
    if not vals:
        return None
    below = sum(1 for v in vals if v < value)
    return round(below / len(vals) * 100, 1)


def _latest_value(series: dict) -> tuple[str | None, float | None]:
    """回 (最新月份, 值)；序列以 YYYYMM 字串為鍵，取最大者。"""
    if not series:
        return None, None
    k = max(series.keys())
    return k, series[k]


async def fetch_valuation_bands(symbol: str) -> dict:
    """A10 相對估值 PE/PB Band（純資料，不呼叫 AI，async httpx，cookie 認證）。

    並行抓 HistoricalPer / HistoricalPbr / PE_Band 三個 cronjob 端點，回：
      {
        "symbol", "stock_name"?,
        "pe": {"latest_month","latest": 本益比, "avg_10y","std_bands":{...},
               "percentile_in_history": %, "peer_median": 同業中位數},
        "pb": {"latest_month","latest": 股價淨值比, "avg_10y","std_bands":{...},
               "percentile_in_history": %},
      }
    三段各自 best-effort；全空回 error dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    cookies, headers = _auth.cookie_context()

    async def _get(endpoint: str) -> dict | None:
        try:
            url = f"{CRONJOB_BASE_URL}/data_fetch/api/{endpoint}/{symbol}"
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                r = await client.get(url, cookies=cookies, headers=headers)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.warning("fetch_valuation_bands %s failed for %s: %s", endpoint, symbol, e)
        return None

    per_json, pbr_json, band_json = await asyncio.gather(
        _get("HistoricalPer"), _get("HistoricalPbr"), _get("PE_Band")
    )

    result: dict = {"symbol": symbol}

    # --- 本益比段 ---
    if per_json:
        series = _parse_ratio_series(per_json, "本益比")
        month, latest = _latest_value(series)
        refline = _parse_refline(per_json)
        pe: dict = {}
        if latest is not None:
            pe["latest_month"] = month
            pe["latest"] = latest
            pct = _percentile_rank(series, latest)
            if pct is not None:
                pe["percentile_in_history"] = pct
        # refline：10年平均 + ±標準差帶（平台預算）
        std_bands = {}
        for label, val in refline.items():
            if "平均" in label:
                pe["avg_10y"] = val
            elif "標準差" in label:
                std_bands[label] = val
        if std_bands:
            pe["std_bands"] = std_bands
        # 同業中位數在 PE_Band 的 refdata（非 HistoricalPer）
        if band_json:
            refdata = (band_json.get("data") or {}).get("refdata") or {}
            if isinstance(refdata, dict):
                for row in refdata.values():
                    if isinstance(row, dict) and "同產業" in row.get("ChineseAccount", ""):
                        if isinstance(row.get("Data"), (int, float)):
                            pe["peer_median"] = row["Data"]
                        break
        # 帶回公司名（best-effort）
        name = (per_json.get("data") or {}).get("stock_name")
        if name:
            result["stock_name"] = name
        if pe:
            result["pe"] = pe

    # --- 股價淨值比段 ---
    if pbr_json:
        series = _parse_ratio_series(pbr_json, "股價淨值比")
        month, latest = _latest_value(series)
        refline = _parse_refline(pbr_json)
        pb: dict = {}
        if latest is not None:
            pb["latest_month"] = month
            pb["latest"] = latest
            pct = _percentile_rank(series, latest)
            if pct is not None:
                pb["percentile_in_history"] = pct
        std_bands = {}
        for label, val in refline.items():
            if "平均" in label:
                pb["avg_10y"] = val
            elif "標準差" in label:
                std_bands[label] = val
        if std_bands:
            pb["std_bands"] = std_bands
        if pb:
            result["pb"] = pb

    if "pe" not in result and "pb" not in result:
        return {"error": f"查無 {symbol} 的估值 PE/PB 資料"}
    return result


# ── A11 三大法人籌碼（cronjob，cookie 認證；純資料不呼叫 AI）──────────────────
# bot 目前完全沒有籌碼面。InstitutionalInvestorsNet 回每日外資/投信/自營商/合計
# 買賣超（張），list 最新在前。本函式取最近 recent 天 + 近 recent 天合計。
# 欄位對照（column_title）：raw80050=外資 raw80053=投信 raw80062=自營商 raw80063=合計。


async def fetch_institutional_chips(symbol: str, recent: int = 20) -> dict:
    """A11 三大法人買賣超（純資料，不呼叫 AI，async httpx，cookie 認證）。

    來源 cronjob `InstitutionalInvestorsNet/{symbol}`：list（最新在前），每筆
    {row_title_center: 日期(YYYYMMDD), raw80050: 外資, raw80053: 投信,
     raw80062: 自營商, raw80063: 三大法人合計}（單位：張）。

    回：
      {
        "symbol", "stock_name"?, "unit": "張",
        "recent_days": [{"date","外資","投信","自營商","合計"}, ...],  # 最新在前，最多 recent 筆
        "sum_recent": {"天數","外資","投信","自營商","合計"},          # 近 recent 天加總
      }
    無資料回 error dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/InstitutionalInvestorsNet/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, cookies=cookies, headers=headers)
    except Exception as e:
        logger.warning("fetch_institutional_chips failed for %s: %s", symbol, e)
        return {"error": f"查無 {symbol} 的三大法人資料"}

    if r.status_code != 200:
        return {"error": f"查無 {symbol} 的三大法人資料"}

    data = (r.json().get("data") or {})
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return {"error": f"查無 {symbol} 的三大法人資料"}

    # 欄位代碼 → 中文（固定，亦可從 column_title 解，這裡直接寫死以求穩定）。
    _F = {"raw80050": "外資", "raw80053": "投信", "raw80062": "自營商", "raw80063": "合計"}

    def _num(v):
        return v if isinstance(v, (int, float)) else 0.0

    recent_days: list[dict] = []
    totals = {"外資": 0.0, "投信": 0.0, "自營商": 0.0, "合計": 0.0}
    for row in rows[:recent]:  # list 最新在前
        if not isinstance(row, dict):
            continue
        entry = {"date": row.get("row_title_center")}
        for code, name in _F.items():
            val = _num(row.get(code))
            entry[name] = val
            totals[name] += val
        recent_days.append(entry)

    if not recent_days:
        return {"error": f"查無 {symbol} 的三大法人資料"}

    result: dict = {"symbol": symbol, "unit": "張", "recent_days": recent_days}
    if data.get("stock_name"):
        result["stock_name"] = data["stock_name"]
    result["sum_recent"] = {
        "天數": len(recent_days),
        "外資": round(totals["外資"], 2),
        "投信": round(totals["投信"], 2),
        "自營商": round(totals["自營商"], 2),
        "合計": round(totals["合計"], 2),
    }
    return result


# ── A12 利潤率趨勢（cronjob，cookie 認證；純資料不呼叫 AI）─────────────────────
# MajorProfitMargins 回毛利率/營業利益率/稅後淨利率的季度序列（key 如 2026Q2）。
# 補現有只有 EPS/營收、缺獲利品質趨勢的缺口。


async def fetch_profit_margins(symbol: str, recent: int = 8) -> dict:
    """A12 三率趨勢：毛利率 / 營業利益率 / 稅後淨利率（純資料，不呼叫 AI）。

    來源 cronjob `MajorProfitMargins/{symbol}`：data.data 為 dict，每列一個率
    （ChineseAccount = 毛利率/營業利益率/稅後淨利率），Data 為 {季度: 值(%)}。
    只取最近 recent 季。

    回：
      {
        "symbol", "stock_name"?, "unit": "%",
        "margins": {
          "毛利率": [{"period","value"}, ...],       # 最舊→最新
          "營業利益率": [...],
          "稅後淨利率": [...],
        },
        "latest": {"period","毛利率","營業利益率","稅後淨利率"},  # 最新一季快照
      }
    無資料回 error dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/MajorProfitMargins/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, cookies=cookies, headers=headers)
    except Exception as e:
        logger.warning("fetch_profit_margins failed for %s: %s", symbol, e)
        return {"error": f"查無 {symbol} 的利潤率資料"}

    if r.status_code != 200:
        return {"error": f"查無 {symbol} 的利潤率資料"}

    data = (r.json().get("data") or {})
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, dict) or not rows:
        return {"error": f"查無 {symbol} 的利潤率資料"}

    wanted = ("毛利率", "營業利益率", "稅後淨利率")
    margins: dict = {}
    latest: dict = {}
    for row in rows.values():
        if not isinstance(row, dict):
            continue
        label = row.get("ChineseAccount", "")
        if label not in wanted:
            continue
        series = row.get("Data", {})
        pairs = _latest_periods(series, recent)  # [(period, value)]，最舊→最新
        if not pairs:
            continue
        margins[label] = [{"period": p, "value": v} for p, v in pairs]
        latest[label] = pairs[-1][1]
        latest["period"] = pairs[-1][0]

    if not margins:
        return {"error": f"查無 {symbol} 的利潤率資料"}

    result: dict = {"symbol": symbol, "unit": "%", "margins": margins}
    if data.get("stock_name"):
        result["stock_name"] = data["stock_name"]
    if latest:
        result["latest"] = latest
    return result


# ── A13 現金流趨勢（cronjob，cookie 認證；純資料不呼叫 AI）─────────────────────
# CashFlowTrend 回營業/投資/籌資/自由現金流的季度序列。注意：資料在 PeriodData
# 欄位（非 Data）。補現有 pershare 只有每股數字、缺總量現金流趨勢的缺口。


def _period_series(row: dict) -> dict:
    """取一列的時間序列：優先 PeriodData，退回 Data；只留數值。"""
    series = row.get("PeriodData")
    if not isinstance(series, dict) or not series:
        series = row.get("Data")
    if not isinstance(series, dict):
        return {}
    return {k: v for k, v in series.items() if isinstance(v, (int, float))}


async def fetch_cash_flow_trend(symbol: str, recent: int = 8) -> dict:
    """A13 現金流趨勢：營業/投資/籌資/自由現金流（純資料，不呼叫 AI）。

    來源 cronjob `CashFlowTrend/{symbol}`：data.data 為 dict，每列一種現金流
    （ChineseAccount = 營業活動現金流/投資活動現金流/籌資活動現金流/自由現金流），
    序列在 PeriodData（{季度: 千元}）。只取最近 recent 季。

    回：
      {
        "symbol", "stock_name"?, "unit": "千元",
        "flows": {"營業活動現金流":[{"period","value"}],"投資活動現金流":[…],
                  "籌資活動現金流":[…],"自由現金流":[…]},
        "latest": {"period","營業活動現金流",…},
      }
    無資料回 error dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/CashFlowTrend/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, cookies=cookies, headers=headers)
    except Exception as e:
        logger.warning("fetch_cash_flow_trend failed for %s: %s", symbol, e)
        return {"error": f"查無 {symbol} 的現金流資料"}

    if r.status_code != 200:
        return {"error": f"查無 {symbol} 的現金流資料"}

    data = (r.json().get("data") or {})
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, dict) or not rows:
        return {"error": f"查無 {symbol} 的現金流資料"}

    wanted = ("營業活動現金流", "投資活動現金流", "籌資活動現金流", "自由現金流")
    flows: dict = {}
    latest: dict = {}
    for row in rows.values():
        if not isinstance(row, dict):
            continue
        label = row.get("ChineseAccount", "")
        if label not in wanted:
            continue
        pairs = _latest_periods(_period_series(row), recent)
        if not pairs:
            continue
        flows[label] = [{"period": p, "value": v} for p, v in pairs]
        latest[label] = pairs[-1][1]
        latest["period"] = pairs[-1][0]

    if not flows:
        return {"error": f"查無 {symbol} 的現金流資料"}

    result: dict = {"symbol": symbol, "unit": "千元", "flows": flows}
    if data.get("stock_name"):
        result["stock_name"] = data["stock_name"]
    if latest:
        result["latest"] = latest
    return result


# ── A14 股利政策（cronjob，cookie 認證；純資料不呼叫 AI）──────────────────────
# CashDividendPayoutRatio 回現金股息合計 + 現金股息發放率(%)，年度序列（Data 欄位）。


async def fetch_dividend_policy(symbol: str, years: int = 10) -> dict:
    """A14 股利政策：現金股息 + 發放率（純資料，不呼叫 AI）。

    來源 cronjob `CashDividendPayoutRatio/{symbol}`：data.data 為 dict，含
    「現金股息合計」與「現金股息發放率％」兩列，Data 為 {年度: 值}。取最近 years 年。

    回：
      {
        "symbol", "stock_name"?,
        "dividends": [{"year","現金股息","發放率(%)"}, ...],   # 最舊→最新
        "latest": {"year","現金股息","發放率(%)"},
      }
    無資料回 error dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/CashDividendPayoutRatio/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, cookies=cookies, headers=headers)
    except Exception as e:
        logger.warning("fetch_dividend_policy failed for %s: %s", symbol, e)
        return {"error": f"查無 {symbol} 的股利資料"}

    if r.status_code != 200:
        return {"error": f"查無 {symbol} 的股利資料"}

    data = (r.json().get("data") or {})
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, dict) or not rows:
        return {"error": f"查無 {symbol} 的股利資料"}

    div_series: dict = {}
    ratio_series: dict = {}
    for row in rows.values():
        if not isinstance(row, dict):
            continue
        label = row.get("ChineseAccount", "")
        series = _period_series(row)
        if "現金股息合計" in label:
            div_series = series
        elif "發放率" in label:
            ratio_series = series

    # 年度聯集，升序。
    years_all = sorted(set(div_series) | set(ratio_series))
    years_all = years_all[-years:]
    if not years_all:
        return {"error": f"查無 {symbol} 的股利資料"}

    dividends = [
        {"year": y, "現金股息": div_series.get(y), "發放率(%)": ratio_series.get(y)}
        for y in years_all
    ]

    result: dict = {"symbol": symbol, "dividends": dividends}
    if data.get("stock_name"):
        result["stock_name"] = data["stock_name"]
    result["latest"] = dividends[-1]
    return result


# ── A15 同業多維比較（組合既有函式；純資料不呼叫 AI）──────────────────────────
# 不打新端點，而是：先 fetch_supply_chain 拿同業代號，再對本檔 + 同業各檔並行取
# fetch_valuation_bands（PE/PB）與 fetch_profit_margins（毛利率），組成橫向對照表。
# 這比依賴平台 StockComparisonBubble（實測常空）可靠，且複用已驗證的函式。


async def fetch_peers_comparison(symbol: str, max_peers: int = 5) -> dict:
    """A15 同業多維比較（純資料，不呼叫 AI）。

    流程：fetch_supply_chain(symbol) 取同業清單 → 取本檔 + 前 max_peers 檔同業，
    對每檔並行抓 fetch_valuation_bands + fetch_profit_margins → 組成對照列。

    回：
      {
        "symbol",
        "peers_compared": [代號, ...],       # 實際納入比較的代號（含本檔，本檔在前）
        "rows": [{"stock","本益比","股價淨值比","毛利率","營業利益率","稅後淨利率"}, ...],
      }
    同業清單取不到回 error dict；個別標的取數失敗只該列留空、不影響其他。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    supply = await fetch_supply_chain(symbol)
    peers = supply.get("peers", []) if isinstance(supply, dict) else []
    # 本檔在前，接著同業（去重、去掉本檔自身），最多 max_peers 檔同業。
    codes = [symbol] + [p for p in peers if p != symbol][:max_peers]

    async def _one(code: str) -> dict:
        val, mar = await asyncio.gather(
            fetch_valuation_bands(code),
            fetch_profit_margins(code),
        )
        row: dict = {"stock": code}
        if isinstance(val, dict) and "error" not in val:
            pe = val.get("pe") or {}
            pb = val.get("pb") or {}
            if pe.get("latest") is not None:
                row["本益比"] = pe["latest"]
            if pb.get("latest") is not None:
                row["股價淨值比"] = pb["latest"]
        if isinstance(mar, dict) and "error" not in mar:
            latest = mar.get("latest") or {}
            for k in ("毛利率", "營業利益率", "稅後淨利率"):
                if latest.get(k) is not None:
                    row[k] = latest[k]
        return row

    rows = await asyncio.gather(*[_one(c) for c in codes])

    # 至少要有本檔 + 一個可比項目才有意義；否則回 error。
    has_metric = any(len(r) > 1 for r in rows)
    if not has_metric:
        return {"error": f"查無 {symbol} 的同業比較資料"}

    return {
        "symbol": symbol,
        "peers_compared": codes,
        "rows": list(rows),
    }


# ── A16 信用交易（融資融券）（cronjob，cookie 認證；純資料不呼叫 AI）────────────
# 合併兩端點的日序列：MarginBalanceVSMarginUtilization（融資餘額+使用率）與
# ShortInterestVSShortSellUtilization（融券餘額+使用率）。都用 Data，日期為 key。


async def fetch_margin_trading(symbol: str, recent: int = 10) -> dict:
    """A16 信用交易：融資餘額/使用率 + 融券餘額/使用率（純資料，不呼叫 AI）。

    並行抓兩個 cronjob 端點，各取最近 recent 日，組成每日一列。
    回：
      {
        "symbol", "stock_name"?,
        "recent_days": [{"date","融資餘額","融資使用率(%)","融券餘額","融券使用率(%)"}, ...],  # 最新在前
        "latest": {同上單筆},
      }
    兩段皆 best-effort；全空回 error dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    cookies, headers = _auth.cookie_context()

    async def _get(endpoint: str) -> dict | None:
        try:
            url = f"{CRONJOB_BASE_URL}/data_fetch/api/{endpoint}/{symbol}"
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                r = await client.get(url, cookies=cookies, headers=headers)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.warning("fetch_margin_trading %s failed for %s: %s", endpoint, symbol, e)
        return None

    margin_json, short_json = await asyncio.gather(
        _get("MarginBalanceVSMarginUtilization"),
        _get("ShortInterestVSShortSellUtilization"),
    )

    def _series(payload: dict | None, label_kw: str) -> dict:
        if not payload:
            return {}
        rows = (payload.get("data") or {}).get("data") or {}
        if not isinstance(rows, dict):
            return {}
        for row in rows.values():
            if isinstance(row, dict) and label_kw in row.get("ChineseAccount", ""):
                return _period_series(row)
        return {}

    m_bal = _series(margin_json, "融資餘額")
    m_use = _series(margin_json, "融資使用率")
    s_bal = _series(short_json, "融券餘額")
    s_use = _series(short_json, "融券使用率")

    # 日期聯集，最新在前。
    all_dates = sorted(set(m_bal) | set(m_use) | set(s_bal) | set(s_use), reverse=True)[:recent]
    if not all_dates:
        return {"error": f"查無 {symbol} 的融資融券資料"}

    recent_days = [
        {
            "date": d,
            "融資餘額": m_bal.get(d),
            "融資使用率(%)": m_use.get(d),
            "融券餘額": s_bal.get(d),
            "融券使用率(%)": s_use.get(d),
        }
        for d in all_dates
    ]

    result: dict = {"symbol": symbol, "recent_days": recent_days, "latest": recent_days[0]}
    name = None
    for payload in (margin_json, short_json):
        if payload:
            name = (payload.get("data") or {}).get("stock_name")
            if name:
                break
    if name:
        result["stock_name"] = name
    return result


# ── A17 籌碼結構（cronjob，cookie 認證；純資料不呼叫 AI）──────────────────────
# 合併 MajorInvestorsHoldings（外資/董監持股比率）與 ShareHoldersStatistics
# （股東人數/大戶持股比率）。兩者皆 list（最新在前）+ column_title 代碼→中文。


def _parse_titled_list(payload: dict) -> tuple[list[dict], dict]:
    """回 (rows, code_to_label)。rows 為原始 list（最新在前），label 由 column_title 攤平。"""
    data = payload.get("data") or {}
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        rows = []
    code_to_label: dict = {}
    for item in data.get("column_title") or []:
        if isinstance(item, dict):
            code_to_label.update(item)
    return rows, code_to_label


async def fetch_holder_structure(symbol: str, recent: int = 6) -> dict:
    """A17 籌碼結構：外資/董監持股比率 + 股東人數/大戶持股比率（純資料，不呼叫 AI）。

    並行抓兩個 cronjob list 端點，各取最近 recent 期（月），以 column_title 解碼欄位。
    回：
      {
        "symbol", "stock_name"?,
        "holdings": [{"period","外資持股比率","董監持股比率","400張以上持股比率"}, ...],  # 最新在前
        "shareholders": [{"period","總股東人數(人)","平均持有張數/人","400張以上持股比率(%)",
                          "1000張以上持股比率(%)"}, ...],
        "latest": {"holdings":{…}, "shareholders":{…}},
      }
    兩段皆 best-effort；全空回 error dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    cookies, headers = _auth.cookie_context()

    async def _get(endpoint: str) -> dict | None:
        try:
            url = f"{CRONJOB_BASE_URL}/data_fetch/api/{endpoint}/{symbol}"
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                r = await client.get(url, cookies=cookies, headers=headers)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.warning("fetch_holder_structure %s failed for %s: %s", endpoint, symbol, e)
        return None

    inv_json, sh_json = await asyncio.gather(
        _get("MajorInvestorsHoldings"),
        _get("ShareHoldersStatistics"),
    )

    def _decode_rows(payload: dict | None, keep_labels: set[str]) -> list[dict]:
        """list 每筆以 column_title 解碼，只留 keep_labels 欄位，附 period。"""
        if not payload:
            return []
        rows, code_to_label = _parse_titled_list(payload)
        out: list[dict] = []
        for row in rows[:recent]:  # 最新在前
            if not isinstance(row, dict):
                continue
            entry: dict = {"period": row.get("row_title_center")}
            for code, val in row.items():
                if code == "row_title_center":
                    continue
                label = code_to_label.get(code, code)
                if label in keep_labels:
                    entry[label] = val
            out.append(entry)
        return out

    holdings = _decode_rows(inv_json, {"外資持股比率", "董監持股比率", "400張以上持股比率"})
    shareholders = _decode_rows(
        sh_json,
        {"總股東人數(人)", "平均持有張數/人", "400張以上持股比率(%)", "1000張以上持股比率(%)"},
    )

    if not holdings and not shareholders:
        return {"error": f"查無 {symbol} 的籌碼結構資料"}

    result: dict = {"symbol": symbol}
    name = None
    for payload in (inv_json, sh_json):
        if payload:
            name = (payload.get("data") or {}).get("stock_name")
            if name:
                break
    if name:
        result["stock_name"] = name
    if holdings:
        result["holdings"] = holdings
    if shareholders:
        result["shareholders"] = shareholders
    latest: dict = {}
    if holdings:
        latest["holdings"] = holdings[0]
    if shareholders:
        latest["shareholders"] = shareholders[0]
    if latest:
        result["latest"] = latest
    return result


# ── A 法說會逐字稿（清單走 gidp、全文走 cronjob；純資料不呼叫 AI）─────────────
# 逐字稿全文 ~15K 字：CLI --transcript <代號> <id/date> 回完整 transcript，
# bot 層再依需要做分頁閱讀。


async def fetch_transcript_list(symbol: str) -> dict:
    """法說會逐字稿清單（gidp，GIDP token）。純資料，不呼叫 AI，async httpx。

    來源 gidp `WebStockInfo/{symbol}?country=TW` 的 data.data 中 ChineseAccount=='逐字稿'
    （key ua80305_cp）那一列，其 Data 為 list，每筆 {Data:'2026/07/16', id:'202607162330'}
    （id = 日期 yyyymmdd + 股號）。回 {symbol, transcripts:[{date, id}, ...]}（最新在前，
    來源本身已最新在前）。無資料回 error dict。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}

    try:
        headers = _auth.gidp_headers()
        url = f"{GIDP_BASE_URL}/data_fetch/api/WebStockInfo/{symbol}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"country": "TW"})
    except Exception as e:
        logger.warning("fetch_transcript_list failed for %s: %s", symbol, e)
        return {"error": f"查無 {symbol} 的法說會逐字稿"}

    if r.status_code != 200:
        return {"error": f"查無 {symbol} 的法說會逐字稿"}

    rows = (r.json().get("data") or {}).get("data") or {}
    raw_list = None
    if isinstance(rows, dict):
        for row in rows.values():
            if isinstance(row, dict) and row.get("ChineseAccount") == "逐字稿":
                raw_list = row.get("Data")
                break

    if not isinstance(raw_list, list) or not raw_list:
        return {"error": f"查無 {symbol} 的法說會逐字稿"}

    transcripts: list[dict] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        tid = item.get("id")
        date = item.get("Data")
        if tid:
            transcripts.append({"date": date, "id": str(tid)})

    if not transcripts:
        return {"error": f"查無 {symbol} 的法說會逐字稿"}

    return {"symbol": symbol, "transcripts": transcripts}


async def fetch_transcript_detail(transcript_id: str) -> dict:
    """法說會逐字稿全文（cronjob，cookie 認證）。純資料，不呼叫 AI，async httpx。

    來源 cronjob `TranscriptDetail?id={id}&country=TWN`（注意 country=TWN 非 TW；
    用 cookie_context 四 cookie + Origin/Referer）。實測全文位於 data.data.data 一層，
    含 transcript（全文 ~15K 字）、title、stock、date（yyyymmdd）。
    回 {id, title, date, stock, transcript}。失敗/無全文回 error dict。
    """
    transcript_id = str(transcript_id).strip()
    if not transcript_id:
        return {"error": "無法取得逐字稿全文"}
    if not await _auth.ensure_token():
        return {"error": "無法取得逐字稿全文"}

    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/TranscriptDetail"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(
                url,
                cookies=cookies,
                headers=headers,
                params={"id": transcript_id, "country": "TWN"},
            )
    except Exception as e:
        logger.warning("fetch_transcript_detail failed for %s: %s", transcript_id, e)
        return {"error": "無法取得逐字稿全文"}

    if r.status_code != 200:
        return {"error": "無法取得逐字稿全文"}

    # 全文巢狀在 data.data.data 一層（實測 top: status/state/data；data.data.data 才是內容）。
    inner = (r.json().get("data") or {}).get("data") or {}
    if not isinstance(inner, dict):
        return {"error": "無法取得逐字稿全文"}
    transcript = inner.get("transcript") or ""
    if not transcript:
        return {"error": "無法取得逐字稿全文"}

    return {
        "id": inner.get("id") or transcript_id,
        "title": inner.get("title") or "",
        "date": inner.get("date") or "",
        "stock": inner.get("stock") or "",
        "transcript": transcript,
    }


# ── A18 AI 知識庫問答（data.uanalyze.com.tw/api/chat，JWT，SSE 串流）──────────
# 移植自 extra_scripts/ua.sh 的 chat 指令。可選知識庫（一般/個股深度/投資教學），
# 串流回傳逐塊組成完整回答。與 analyze()（走 twobitto completions）互補：這支能選知識庫。

# chat 回傳含模型思考標記 <think>…</think>，回給使用者/Agent 前濾掉。
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_TAG_RE = re.compile(r"</?(?:think|step)>")


def _strip_think(text: str) -> str:
    """移除 chat 串流的 <think>/<step> 思考標記，回乾淨正文。"""
    text = _THINK_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    return text.strip()


async def fetch_ai_chat(symbol: str, question: str, kb: str = DEFAULT_KB) -> dict:
    """A18 AI 知識庫問答（純資料 CLI，串流收集後回完整答案）。

    Args:
        symbol: 股票代號（如 '2330'）。
        question: 自然語言問題。
        kb: 知識庫別名 general / knowledge / teacher（見 UA_KNOWLEDGE_BASES）。

    Returns:
        {"symbol","question","knowledge_base","answer"} 或 {"error": ...}。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not (question or "").strip():
        return {"error": "請輸入問題"}
    api_name = UA_KNOWLEDGE_BASES.get(kb, kb if kb.startswith("ua_ai_insight_") else UA_KNOWLEDGE_BASES[DEFAULT_KB])

    token = await _auth.ensure_token()
    if not token:
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    url = f"{DATA_API_BASE}/chat/{api_name}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
        "Origin": "https://pro.uanalyze.com.tw",
        "Referer": "https://pro.uanalyze.com.tw/",
        "User-Agent": "Mozilla/5.0",
    }
    params = {"q": question, "stock": symbol, "stream": "true"}

    chunks: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            async with client.stream("GET", url, headers=headers, params=params) as resp:
                if resp.status_code == 401 and await _auth.refresh():
                    headers["Authorization"] = f"Bearer {_auth.access_token}"
                    async with client.stream("GET", url, headers=headers, params=params) as resp2:
                        resp = resp2
                        async for chunk in _collect_chat(resp):
                            chunks.append(chunk)
                elif resp.status_code == 200:
                    async for chunk in _collect_chat(resp):
                        chunks.append(chunk)
                else:
                    return {"error": f"UAnalyze 問答失敗（HTTP {resp.status_code}）"}
    except Exception as e:
        logger.warning("fetch_ai_chat failed for %s: %s", symbol, e)
        return {"error": f"UAnalyze 問答發生錯誤：{e}"}

    answer = _strip_think("".join(chunks))
    if not answer:
        return {"error": f"UAnalyze 未回傳 {symbol} 的問答內容"}
    return {"symbol": symbol, "question": question, "knowledge_base": api_name, "answer": answer}


async def _collect_chat(resp) -> "AsyncIterator[str]":
    """從 SSE 回應逐行取出 type==content 的 chunk。"""
    async for line in resp.aiter_lines():
        if not line.startswith("data: "):
            continue
        try:
            obj = json.loads(line[6:])
        except Exception:
            continue
        if obj.get("type") == "content":
            chunk = obj.get("data", {}).get("chunk", "")
            if chunk:
                yield chunk


# ── A19 批次雷達（cronjob company_keywords，multipart，可數十 MB）─────────────
# 移植自 extra_scripts/uanalyze_radar.py。一次抓多類資料；因回傳可能巨大（transcript
# 可達 30MB+），落地成檔案、只回「檔案路徑 + 每類筆數摘要」，不整包塞回 Agent。

RADAR_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "uanalyze_radar"
)


async def fetch_company_keywords(keyword: str, types: str = DEFAULT_RADAR_TYPES) -> dict:
    """A19 批次雷達：一次抓多類資料，落地成 JSON 檔，回檔案路徑 + 摘要。

    Args:
        keyword: 查詢關鍵字（公司名或代號，如 '台積電' / '2330'）。
        types: 逗號分隔的資料類別（預設 company_info,ai_chat,transcript）。

    Returns:
        {"keyword","types","file","bytes","summary":{類別: 筆數/大小}} 或 {"error": ...}。
        因回傳可能數十 MB，內容寫檔不直接回傳，避免灌爆呼叫端 context。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"error": "請輸入查詢關鍵字"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    url = f"{CRONJOB_BASE_URL}/data_fetch/api/company_keywords/{types}"
    headers = {
        "Accept": "application/json",
        "Origin": "https://pro.uanalyze.com.tw",
        "Referer": "https://pro.uanalyze.com.tw/",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.post(url, headers=headers, files={"data": (None, keyword)})
    except Exception as e:
        logger.warning("fetch_company_keywords failed for %s: %s", keyword, e)
        return {"error": f"UAnalyze 批次雷達發生錯誤：{e}"}

    if r.status_code != 200:
        return {"error": f"UAnalyze 批次雷達失敗（HTTP {r.status_code}）"}

    try:
        payload = r.json()
    except Exception:
        return {"error": "UAnalyze 批次雷達回傳非 JSON"}

    os.makedirs(RADAR_OUTPUT_DIR, exist_ok=True)
    safe_kw = re.sub(r"[^\w\u4e00-\u9fff]+", "_", keyword).strip("_") or "radar"
    out_path = os.path.join(RADAR_OUTPUT_DIR, f"{safe_kw}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    # 摘要：每個資料類別的筆數（data 通常是 dict of 類別 → list/dict）。
    summary: dict = {}
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        for cat, val in data.items():
            if isinstance(val, (list, dict)):
                summary[cat] = len(val)
            else:
                summary[cat] = 1 if val else 0

    return {
        "keyword": keyword,
        "types": types,
        "file": out_path,
        "bytes": len(r.content),
        "summary": summary,
    }


# ── A20 前瞻共識：Reuters SmartEstimate 法人預估（gidp，country=TW）───────────
# 沿用既有 gidp 模式（gidp_headers() + params country=TW），不碰 DCF 取數路徑。
# 每項端點回 3 欄（平均/最低/最高值），年度 key 帶 (f) 後綴（如 2027(f)）。

# SmartEstimate 端點 → 中文短名。全部 gidp domain（cronjob 亦有部分，但 gidp 版齊全）。
_SMART_ESTIMATE_ENDPOINTS: dict[str, str] = {
    "ReutersSmartEstimate_EPS": "EPS",
    "ReutersSmartEstimate_Revenue": "營收",
    "ReutersSmartEstimate_GrossMargin": "毛利率",
    "ReutersSmartEstimate_EBIT": "EBIT",
    "ReutersSmartEstimate_EBITDA": "EBITDA",
    "ReutersSmartEstimate_NetIncome": "稅後淨利",
    "ReutersSmartEstimate_Capex": "資本支出",
    "ReutersSmartEstimate_DividendPerShare": "每股股息",
}


def _clean_num(v: object) -> float | None:
    """SmartEstimate 未來太遠年份常為空字串，轉 None；數字原樣。"""
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return float(v)
        except ValueError:
            return None
    return None


async def fetch_smart_estimate(symbol: str, recent: int = 5) -> dict:
    """A20 前瞻共識：Reuters（Refinitiv）法人預估的平均/最低/最高值（純資料）。

    並行抓 8 個 gidp SmartEstimate 端點（EPS/營收/毛利率/EBIT/EBITDA/淨利/資本支出/
    股息），各取最近 recent 個年度（含未來 (f) 預估年）。

    Returns:
      {
        "symbol", "unit_note",
        "estimates": {"EPS": [{"year","平均","最低","最高"}, ...], "營收": [...], ...},
      }
    全空回 {"error": ...}。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    headers = _auth.gidp_headers()

    async def _get(endpoint: str) -> tuple[str, dict | None]:
        try:
            url = f"{GIDP_BASE_URL}/data_fetch/api/{endpoint}/{symbol}"
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                r = await client.get(url, headers=headers, params={"country": "TW"})
            if r.status_code == 200:
                return endpoint, r.json()
        except Exception as e:
            logger.warning("fetch_smart_estimate %s failed for %s: %s", endpoint, symbol, e)
        return endpoint, None

    results = await asyncio.gather(*[_get(ep) for ep in _SMART_ESTIMATE_ENDPOINTS])

    estimates: dict = {}
    for endpoint, payload in results:
        label = _SMART_ESTIMATE_ENDPOINTS[endpoint]
        if not payload:
            continue
        rows = (payload.get("data") or {}).get("data") or {}
        if not isinstance(rows, dict):
            continue
        # refinitiv_1=平均, _2=最低, _3=最高（依 ChineseAccount 判斷更穩）。
        avg = low = high = {}
        for row in rows.values():
            if not isinstance(row, dict):
                continue
            nm = row.get("ChineseAccount", "")
            data_map = row.get("Data", {})
            if "平均" in nm:
                avg = data_map
            elif "最低" in nm:
                low = data_map
            elif "最高" in nm:
                high = data_map
        years = sorted(set(avg) | set(low) | set(high))[-recent:]
        series = [
            {
                "year": y,
                "平均": _clean_num(avg.get(y)),
                "最低": _clean_num(low.get(y)),
                "最高": _clean_num(high.get(y)),
            }
            for y in years
        ]
        if series:
            estimates[label] = series

    if not estimates:
        return {"error": f"查無 {symbol} 的法人前瞻預估資料"}
    return {
        "symbol": symbol,
        "unit_note": "營收/EBIT/EBITDA/淨利為千元；EPS/每股股息為元；毛利率為 %；(f) 為預估年度",
        "estimates": estimates,
    }


# ── A21 前瞻共識：未來五季預估路徑 + 評等佔比趨勢（gidp，country=TW）──────────


async def fetch_forecast_route(symbol: str, recent: int = 6) -> dict:
    """A21 未來五季 營收/EPS/毛利率/營益率 預估路徑 + 分析師評等佔比趨勢（純資料）。

    Returns:
      {
        "symbol",
        "route": {"未來五季營收預估路徑":[{"period","value"}], "未來五季EPS預估路徑":[...],
                  "未來五季毛利率預估路徑":[...], "未來五季營業利益率預估路徑":[...]},
        "rating_trend": [{"month","樂觀","中立","悲觀","收盤價"}, ...],  # 近 recent 月
      }
    全空回 {"error": ...}。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}

    headers = _auth.gidp_headers()

    async def _get(endpoint: str) -> dict | None:
        try:
            url = f"{GIDP_BASE_URL}/data_fetch/api/{endpoint}/{symbol}"
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                r = await client.get(url, headers=headers, params={"country": "TW"})
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.warning("fetch_forecast_route %s failed for %s: %s", endpoint, symbol, e)
        return None

    eps_rev_json, margin_json, rating_json = await asyncio.gather(
        _get("QEPSRevenueConsensusEstimateRoute"),
        _get("QMargingsConsensusEstimateRoute"),
        _get("AnalystRatingChangeTrend"),
    )

    route: dict = {}

    def _add_routes(payload: dict | None) -> None:
        if not payload:
            return
        rows = (payload.get("data") or {}).get("data") or {}
        if not isinstance(rows, dict):
            return
        for row in rows.values():
            if not isinstance(row, dict):
                continue
            nm = row.get("ChineseAccount", "")
            data_map = row.get("Data", {})
            if nm and data_map:
                route[nm] = [
                    {"period": p, "value": _clean_num(v)} for p, v in _latest_periods(data_map, 5)
                ]

    _add_routes(eps_rev_json)
    _add_routes(margin_json)

    # 評等佔比趨勢
    rating_trend: list[dict] = []
    if rating_json:
        rows = (rating_json.get("data") or {}).get("data") or {}
        if isinstance(rows, dict):
            opt = mid = pess = price = {}
            for row in rows.values():
                if not isinstance(row, dict):
                    continue
                nm = row.get("ChineseAccount", "")
                dm = row.get("Data", {})
                if "樂觀" in nm:
                    opt = dm
                elif "中立" in nm:
                    mid = dm
                elif "悲觀" in nm:
                    pess = dm
                elif "收盤價" in nm:
                    price = dm
            months = sorted(set(opt) | set(mid) | set(pess))[-recent:]
            rating_trend = [
                {
                    "month": m,
                    "樂觀": _clean_num(opt.get(m)),
                    "中立": _clean_num(mid.get(m)),
                    "悲觀": _clean_num(pess.get(m)),
                    "收盤價": _clean_num(price.get(m)),
                }
                for m in months
            ]

    if not route and not rating_trend:
        return {"error": f"查無 {symbol} 的預估路徑/評等資料"}
    result: dict = {"symbol": symbol}
    if route:
        result["route"] = route
    if rating_trend:
        result["rating_trend"] = rating_trend
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

    if args[0] == "--multi":
        # 一次並行跑多個面向：--multi <代號> --prompts a,b,c [--concurrency N]
        # 面向由 Agent 自行決定並以逗號分隔傳入；本工具不寫死清單。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --multi <代號> --prompts a,b,c [--concurrency N]"}, ensure_ascii=False))
            sys.exit(1)
        prompts: list[str] = []
        if "--prompts" in args:
            try:
                prompts = [p for p in args[args.index("--prompts") + 1].split(",") if p.strip()]
            except IndexError:
                pass
        concurrency = DEFAULT_MULTI_CONCURRENCY
        if "--concurrency" in args:
            try:
                concurrency = int(args[args.index("--concurrency") + 1])
            except (IndexError, ValueError):
                pass
        result = asyncio.run(analyze_multi(sym, prompts, concurrency))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

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

    if args[0] == "--fundamentals":
        # A9 即時基本面摘要（附加在 /p；best-effort，無資料回 {}）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --fundamentals <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_stock_fundamentals(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)

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

    if args[0] == "--valuation":
        # A10 相對估值 PE/PB Band 摘要（Agent 用；純資料，不呼叫 AI）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --valuation <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_valuation_bands(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--chips":
        # A11 三大法人買賣超摘要（Agent 用；純資料，不呼叫 AI）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --chips <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_institutional_chips(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--margins":
        # A12 三率趨勢（毛利率/營業利益率/稅後淨利率）摘要（Agent 用；純資料，不呼叫 AI）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --margins <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_profit_margins(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--cashflow":
        # A13 現金流趨勢摘要（Agent 用；純資料，不呼叫 AI）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --cashflow <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_cash_flow_trend(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--dividend":
        # A14 股利政策摘要（Agent 用；純資料，不呼叫 AI）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --dividend <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_dividend_policy(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--peers-compare":
        # A15 同業多維比較摘要（Agent 用；組合既有函式，純資料，不呼叫 AI）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --peers-compare <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_peers_comparison(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--margin":
        # A16 信用交易（融資融券）摘要（Agent 用；純資料，不呼叫 AI）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --margin <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_margin_trading(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--holders":
        # A17 籌碼結構（持股比率/股東結構）摘要（Agent 用；純資料，不呼叫 AI）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --holders <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_holder_structure(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--transcript":
        # A 法說會逐字稿：
        #   --transcript <代號>            → 列該股歷次逐字稿清單（日期 + id）
        #   --transcript <代號> <id 或 date> → 回該篇全文（title+date+字數+完整 transcript）
        try:
            sym = args[1]
        except IndexError:
            print(
                json.dumps(
                    {"error": "用法: python tools/uanalyze.py --transcript <代號> [id 或 date]"},
                    ensure_ascii=False,
                )
            )
            sys.exit(1)

        selector = args[2] if len(args) > 2 else None
        if not selector:
            # 列清單
            result = asyncio.run(fetch_transcript_list(sym))
            print(json.dumps(result, ensure_ascii=False))
            sys.exit(1 if "error" in result else 0)

        # 帶 selector：先列清單解析出目標 id（支援直接給 id 或給 date），再取摘要。
        listing = asyncio.run(fetch_transcript_list(sym))
        if "error" in listing:
            print(json.dumps(listing, ensure_ascii=False))
            sys.exit(1)

        target_id = None
        for t in listing.get("transcripts", []):
            if selector == t.get("id") or selector == t.get("date"):
                target_id = t.get("id")
                break
        # 若使用者直接給了看起來像 id 的字串（12 碼數字），也允許直接用。
        if target_id is None and selector.isdigit() and len(selector) >= 10:
            target_id = selector
        if target_id is None:
            print(
                json.dumps(
                    {"error": f"查無 {sym} 對應 {selector} 的逐字稿"}, ensure_ascii=False
                )
            )
            sys.exit(1)

        detail = asyncio.run(fetch_transcript_detail(target_id))
        if "error" in detail:
            print(json.dumps(detail, ensure_ascii=False))
            sys.exit(1)

        full = detail.get("transcript", "")
        result = {
            "id": detail.get("id"),
            "title": detail.get("title"),
            "date": detail.get("date"),
            "stock": detail.get("stock"),
            "字數": len(full),
            "transcript": full,
        }
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)

    if args[0] == "--ask":
        # A18 AI 知識庫問答：--ask <代號> "<問題>" [知識庫 general|knowledge|teacher]
        try:
            sym = args[1]
            question = args[2]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --ask <代號> \"<問題>\" [general|knowledge|teacher]"}, ensure_ascii=False))
            sys.exit(1)
        kb = args[3] if len(args) > 3 else DEFAULT_KB
        result = asyncio.run(fetch_ai_chat(sym, question, kb))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--radar":
        # A19 批次雷達：--radar <關鍵字> [types逗號分隔]。落地成檔，回路徑+摘要。
        try:
            kw = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --radar <關鍵字> [types]"}, ensure_ascii=False))
            sys.exit(1)
        types = args[2] if len(args) > 2 else DEFAULT_RADAR_TYPES
        result = asyncio.run(fetch_company_keywords(kw, types))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--smart-estimate":
        # A20 前瞻共識：法人 SmartEstimate 平均/最低/最高值（Agent 用；純資料）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --smart-estimate <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_smart_estimate(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    if args[0] == "--forecast-route":
        # A21 前瞻共識：未來五季預估路徑 + 評等佔比趨勢（Agent 用；純資料）。
        try:
            sym = args[1]
        except IndexError:
            print(json.dumps({"error": "用法: python tools/uanalyze.py --forecast-route <代號>"}, ensure_ascii=False))
            sys.exit(1)
        result = asyncio.run(fetch_forecast_route(sym))
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1 if "error" in result else 0)

    result = asyncio.run(analyze(symbol, prompt))
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
