"""raw.uanalyze — UAnalyze 各 API 端點的純資料抓取層（一端點一 function）。

分層原則（見 docs/todo/projects/03-tools-raw-analysis-split/spec.md）：
  - 本模組只負責「抓一個端點的原始資料」，回最完整的原始結構，**不判讀、不跨端點組合、不計算**。
  - 認證固定：每個端點用其唯一正確的 domain/認證（cronjob cookie / gidp 固定 token / jwt）。
  - 「怎麼用、怎麼組合、怎麼算」是 analysis 層與 Agent 的事。

認證：一次帳密登入（UAnalyzeAuth.login）後，依 domain 取三種認證材料：
  - jwt_headers():    data.uanalyze.twobitto.com / api.uanalyze.com.tw（Bearer access_token）
  - cookie_context(): cronjob.uanalyze.com.tw（記憶體 4-cookie + Origin/Referer）
  - gidp_headers():   gidp.uanalyze.com.tw（前端寫死的固定 GIDP token）

CLI（Agent 直接跑；一律回原始 JSON，失敗回 {"error"}）:
  python tools/raw/uanalyze.py <fetcher 名> <參數...>

可用 fetcher（名稱 = 去掉 fetch_raw_ 前綴；多數帶股票代號）：

  【估值 / 每股】
    historical_per <代號>          本益比月序列（近20年，cronjob）
    historical_pbr <代號>          股價淨值比月序列
    pe_band <代號>                 PE Band（含 refdata 同業本益比中位數）
    per_share_value <代號>         每股 FCF/EPS/ROE/ROIC… 多年表
  【籌碼 / 法人】
    institutional_net <代號>       三大法人買賣超（含 column_title）
    margin_balance <代號>          融資餘額/使用率
    short_interest <代號>          融券餘額/使用率
    major_investors_holdings <代號> 外資/董監持股比率（list+column_title）
    shareholders_stats <代號>      股東人數/大戶比率（list+column_title）
  【獲利 / 現金流 / 股利】
    profit_margins <代號>          三率（毛利率/營益率/淨利率）
    cash_flow_trend <代號>         營業/投資/籌資/自由現金流（PeriodData）
    cash_dividend_payout <代號>    現金股息/發放率
  【法人共識 / 前瞻預估】
    eps_revenue_consensus <代號>   年度 營收/EPS/本業EPS 共識（含 (f) 預估年）
    revenue_tracking <代號>        月營收共識追蹤
    eps_tracking <代號>            單季 EPS 實際 vs 法人共識
    broker_eps_table <代號>        全市場各券商逐年預估 EPS（未過濾，需自挑本檔）
    smart_estimate <代號>          Reuters 8 指標法人預估（平均/最低/最高）
    eps_route <代號>               未來五季 營收/EPS 預估路徑
    margin_route <代號>            未來五季 毛利率/營益率 預估路徑
    rating_trend <代號>            分析師評等佔比趨勢
  【同業 / 訂單 / 基本面 / 逐字稿】
    stock_comparison_pool <代號>   同業/供應鏈標的池
    order_visibility <代號>        訂單能見度+合約負債（全市場排行，需自挑本檔）
    web_stock_info <代號>          即時基本面 + 逐字稿清單
    transcript_detail <逐字稿id>   法說會逐字稿全文
  【報告 / AI（呼叫外部 AI，仍屬取數）/ 批次】
    report_summaries [代號] [limit] [offset]  研究報告摘要（帶代號=單股；不帶=全站最新，推播用）
    completion <代號> <prompt>     UAnalyze AI 分析（單面向）
    ai_chat <代號> <問題> [知識庫]  AI 知識庫問答（general/knowledge/teacher；回原始 chunks+answer，未濾 <think>）
    company_keywords <關鍵字> [types]  批次雷達（多類全站資料，回原始 payload，可數十 MB）

  例:
    python tools/raw/uanalyze.py historical_per 2330
    python tools/raw/uanalyze.py report_summaries            # 全站最新（推播監控）
    python tools/raw/uanalyze.py ai_chat 2330 "近況如何" knowledge

Agent 使用方式（重要）：raw 層只回**原始資料**、不判讀不組合。要「法人共識報告」「同業比較」
這類組合，Agent 自行 call 多個 fetcher 再自己整理；要「DCF / PE Band 百分位」這類計算，
用 analysis 層（tools/analysis/valuation.py），別自己重算。

回傳：一律原始 JSON dict/list（或 {"error": str}）。
"""

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

AUTH_BASE_URL = os.getenv("UANALYZE_AUTH_URL", "https://api.uanalyze.com.tw")
BASE_URL = "https://data.uanalyze.twobitto.com"
DATA_API_BASE = "https://data.uanalyze.com.tw/api"
CRONJOB_BASE_URL = "https://cronjob.uanalyze.com.tw"
GIDP_BASE_URL = "https://gidp.uanalyze.com.tw"
GIDP_TOKEN = "tquEQGIZfck2lYDdBst9LBF5p6jfQepV"
DEFAULT_TIMEOUT = 120.0

# AI 問答知識庫（chat 端點）。短別名 → 完整 api_name。
UA_KNOWLEDGE_BASES: dict[str, str] = {
    "general": "ua_ai_insight_general",
    "knowledge": "ua_ai_insight_knowledge",
    "teacher": "ua_ai_insight_teacher",
}
DEFAULT_KB = "general"

# company_keywords 批次雷達預設抓的資料類別。
DEFAULT_RADAR_TYPES = "company_info,ai_chat,transcript"


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
                    self.token_type = payload.get("token_type")
                    self.expires_in = payload.get("expires_in")
                    return bool(self.access_token)
                logger.warning("UAnalyze login failed: HTTP %d", r.status_code)
                return False
        except Exception as e:
            logger.error("UAnalyze login error: %s", e)
            return False

    async def refresh(self) -> bool:
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
        if self.access_token:
            return self.access_token
        if await self.login():
            return self.access_token
        return None

    def jwt_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://pro.uanalyze.com.tw/",
        }

    def cookie_context(self) -> tuple[dict, dict]:
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
        return {
            "Authorization": f"Bearer {GIDP_TOKEN}",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://pro.uanalyze.com.tw/",
        }


# Module-level auth instance (reused across calls)
_auth = UAnalyzeAuth()

ERR_NO_LOGIN = {"error": "UAnalyze 登入失敗（請確認 UANALYZE_EMAIL / UANALYZE_PASSWORD）"}


# ── 共用取數 helper ────────────────────────────────────────────────────────
# 每個 raw fetcher 只做：ensure_token → 打一個端點 → 回原始 json（data 內層）。


async def _get_cronjob(endpoint: str, symbol: str) -> dict | None:
    """打一個 cronjob /data_fetch/api/<endpoint>/<symbol>，回原始 json（含 data 包裝）。"""
    cookies, headers = _auth.cookie_context()
    url = f"{CRONJOB_BASE_URL}/data_fetch/api/{endpoint}/{symbol}"
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        r = await client.get(url, cookies=cookies, headers=headers)
    return r.json() if r.status_code == 200 else None


async def _get_gidp(endpoint: str, symbol: str = "", params: dict | None = None) -> dict | None:
    """打一個 gidp /data_fetch/api/<endpoint>[/<symbol>]，帶 country=TW，回原始 json。"""
    headers = _auth.gidp_headers()
    path = f"{endpoint}/{symbol}" if symbol else endpoint
    url = f"{GIDP_BASE_URL}/data_fetch/api/{path}"
    q = {"country": "TW"}
    if params:
        q.update(params)
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        r = await client.get(url, headers=headers, params=q)
    return r.json() if r.status_code == 200 else None


def _unwrap(payload: dict | None) -> dict | list | None:
    """取 data.data（多數端點的實際序列所在）。取不到回 None。"""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        return data.get("data")
    return None


# ══════════════════════════════════════════════════════════════════════════
# raw fetchers — cronjob domain（cookie 認證）
# ══════════════════════════════════════════════════════════════════════════


async def fetch_raw_historical_per(symbol: str) -> dict:
    """本益比月序列（HistoricalPer，cronjob——237 筆近20年，較 gidp 完整）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_cronjob("HistoricalPer", symbol))
    except Exception as e:
        logger.warning("fetch_raw_historical_per %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的本益比資料"}


async def fetch_raw_historical_pbr(symbol: str) -> dict:
    """股價淨值比月序列（HistoricalPbr，cronjob）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_cronjob("HistoricalPbr", symbol))
    except Exception as e:
        logger.warning("fetch_raw_historical_pbr %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的股價淨值比資料"}


async def fetch_raw_pe_band(symbol: str) -> dict:
    """PE Band（PE_Band，cronjob；含 refdata 同業本益比中位數）。回**整包 data**（含 refdata）。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        payload = await _get_cronjob("PE_Band", symbol)
    except Exception as e:
        logger.warning("fetch_raw_pe_band %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {"error": f"查無 {symbol} 的 PE Band 資料"}


async def fetch_raw_per_share_value(symbol: str) -> dict:
    """每股財務指標多年表（PerShareValueForValuationModel，cronjob）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_cronjob("PerShareValueForValuationModel", symbol))
    except Exception as e:
        logger.warning("fetch_raw_per_share_value %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的每股指標資料"}


async def fetch_raw_stock_comparison_pool(symbol: str) -> dict:
    """同業/供應鏈標的池（StockComparisonStockPool，cronjob）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        payload = await _get_cronjob("StockComparisonStockPool", symbol)
    except Exception as e:
        logger.warning("fetch_raw_stock_comparison_pool %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {"error": f"查無 {symbol} 的同業池資料"}


async def fetch_raw_institutional_net(symbol: str) -> dict:
    """三大法人買賣超（InstitutionalInvestorsNet，cronjob）。回**整包 data**（含 column_title）。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        payload = await _get_cronjob("InstitutionalInvestorsNet", symbol)
    except Exception as e:
        logger.warning("fetch_raw_institutional_net %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {"error": f"查無 {symbol} 的三大法人資料"}


async def fetch_raw_profit_margins(symbol: str) -> dict:
    """三率（MajorProfitMargins，cronjob；毛利率/營益率/淨利率）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_cronjob("MajorProfitMargins", symbol))
    except Exception as e:
        logger.warning("fetch_raw_profit_margins %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的三率資料"}


async def fetch_raw_cash_flow_trend(symbol: str) -> dict:
    """現金流趨勢（CashFlowTrend，cronjob；資料在 PeriodData）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_cronjob("CashFlowTrend", symbol))
    except Exception as e:
        logger.warning("fetch_raw_cash_flow_trend %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的現金流資料"}


async def fetch_raw_cash_dividend_payout(symbol: str) -> dict:
    """現金股息/發放率（CashDividendPayoutRatio，cronjob）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_cronjob("CashDividendPayoutRatio", symbol))
    except Exception as e:
        logger.warning("fetch_raw_cash_dividend_payout %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的股利資料"}


async def fetch_raw_margin_balance(symbol: str) -> dict:
    """融資餘額/使用率（MarginBalanceVSMarginUtilization，cronjob）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        payload = await _get_cronjob("MarginBalanceVSMarginUtilization", symbol)
    except Exception as e:
        logger.warning("fetch_raw_margin_balance %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {"error": f"查無 {symbol} 的融資資料"}


async def fetch_raw_short_interest(symbol: str) -> dict:
    """融券餘額/使用率（ShortInterestVSShortSellUtilization，cronjob）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        payload = await _get_cronjob("ShortInterestVSShortSellUtilization", symbol)
    except Exception as e:
        logger.warning("fetch_raw_short_interest %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {"error": f"查無 {symbol} 的融券資料"}


async def fetch_raw_major_investors_holdings(symbol: str) -> dict:
    """外資/董監持股比率（MajorInvestorsHoldings，cronjob；list+column_title）。回整包 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        payload = await _get_cronjob("MajorInvestorsHoldings", symbol)
    except Exception as e:
        logger.warning("fetch_raw_major_investors_holdings %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {"error": f"查無 {symbol} 的持股比率資料"}


async def fetch_raw_shareholders_stats(symbol: str) -> dict:
    """股東人數/大戶比率（ShareHoldersStatistics，cronjob；list+column_title）。回整包 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        payload = await _get_cronjob("ShareHoldersStatistics", symbol)
    except Exception as e:
        logger.warning("fetch_raw_shareholders_stats %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {"error": f"查無 {symbol} 的股東結構資料"}


async def fetch_raw_transcript_detail(transcript_id: str) -> dict:
    """法說會逐字稿全文（TranscriptDetail?id=&country=TWN，cronjob）。回原始巢狀 json。"""
    tid = (transcript_id or "").strip()
    if not tid:
        return {"error": "請輸入逐字稿 id"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        cookies, headers = _auth.cookie_context()
        url = f"{CRONJOB_BASE_URL}/data_fetch/api/TranscriptDetail"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, cookies=cookies, headers=headers,
                                  params={"id": tid, "country": "TWN"})
        if r.status_code != 200:
            return {"error": f"逐字稿取數失敗（HTTP {r.status_code}）"}
        return r.json()
    except Exception as e:
        logger.warning("fetch_raw_transcript_detail %s: %s", tid, e)
        return {"error": f"取數失敗：{e}"}


# ══════════════════════════════════════════════════════════════════════════
# raw fetchers — gidp domain（固定 GIDP token）
# ══════════════════════════════════════════════════════════════════════════


async def fetch_raw_eps_revenue_consensus(symbol: str) -> dict:
    """年度營收/EPS/本業EPS 共識（EPSRevenueConsensusEstimate，gidp）。回原始 data。

    含 ua50189_cp(營收)/ua50187_cp(EPS)/ua50209_cp(本業EPS)，年份 key 帶 (f) 為預估。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_gidp("EPSRevenueConsensusEstimate", symbol))
    except Exception as e:
        logger.warning("fetch_raw_eps_revenue_consensus %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的年度共識資料"}


async def fetch_raw_revenue_tracking(symbol: str) -> dict:
    """月營收共識追蹤（MonthlyRevenueTrackingConcensuslModule，gidp）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_gidp("MonthlyRevenueTrackingConcensuslModule", symbol))
    except Exception as e:
        logger.warning("fetch_raw_revenue_tracking %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的月營收共識資料"}


async def fetch_raw_eps_tracking(symbol: str) -> dict:
    """單季 EPS 實際 vs 法人共識（EPSTrackingActualVSForecastModule，cronjob）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_cronjob("EPSTrackingActualVSForecastModule", symbol))
    except Exception as e:
        logger.warning("fetch_raw_eps_tracking %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的單季EPS資料"}


async def fetch_raw_broker_eps_table(symbol: str) -> dict:
    """全市場各券商逐年預估 EPS（EPSFilterTableE0001，gidp；需自行以 stock_code 過濾）。

    回原始 data（以發布日期為鍵的全市場資料，未過濾——過濾/挑本檔是消費者的事）。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_gidp("EPSFilterTableE0001"))
    except Exception as e:
        logger.warning("fetch_raw_broker_eps_table %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": "查無各券商 EPS 明細資料"}


async def fetch_raw_order_visibility(symbol: str) -> dict:
    """訂單能見度+合約負債（OrderVisibilitySingleRankings，gidp；全市場排行，需過濾本檔）。

    回**整包 data**（含 column_title + data list，過濾本檔是消費者的事）。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        payload = await _get_gidp("OrderVisibilitySingleRankings")
    except Exception as e:
        logger.warning("fetch_raw_order_visibility %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {"error": "查無訂單能見度資料"}


async def fetch_raw_web_stock_info(symbol: str) -> dict:
    """即時基本面 + 逐字稿清單（WebStockInfo，gidp）。回原始 data（各欄 ChineseAccount+Data）。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_gidp("WebStockInfo", symbol))
    except Exception as e:
        logger.warning("fetch_raw_web_stock_info %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的即時基本面資料"}


# Reuters SmartEstimate（gidp）8 端點 → 端點常數，供 fetch_raw_smart_estimate 逐一抓。
SMART_ESTIMATE_ENDPOINTS: dict[str, str] = {
    "ReutersSmartEstimate_EPS": "EPS",
    "ReutersSmartEstimate_Revenue": "營收",
    "ReutersSmartEstimate_GrossMargin": "毛利率",
    "ReutersSmartEstimate_EBIT": "EBIT",
    "ReutersSmartEstimate_EBITDA": "EBITDA",
    "ReutersSmartEstimate_NetIncome": "稅後淨利",
    "ReutersSmartEstimate_Capex": "資本支出",
    "ReutersSmartEstimate_DividendPerShare": "每股股息",
}


async def fetch_raw_smart_estimate(symbol: str) -> dict:
    """Reuters SmartEstimate 8 指標法人預估（gidp，並行抓）。回 {端點中文名: 原始data} dict。

    每個端點 3 欄（平均/最低/最高值），年度 key 帶 (f)。空字串等原始值原樣保留。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)

    async def _one(endpoint: str, label: str) -> tuple[str, dict | None]:
        try:
            return label, _unwrap(await _get_gidp(endpoint, symbol))
        except Exception as e:
            logger.warning("fetch_raw_smart_estimate %s %s: %s", endpoint, symbol, e)
            return label, None

    results = await asyncio.gather(
        *[_one(ep, label) for ep, label in SMART_ESTIMATE_ENDPOINTS.items()]
    )
    out = {label: data for label, data in results if isinstance(data, dict) and data}
    return out if out else {"error": f"查無 {symbol} 的法人前瞻預估資料"}


async def fetch_raw_eps_route(symbol: str) -> dict:
    """未來五季營收/EPS 預估路徑（QEPSRevenueConsensusEstimateRoute，gidp）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_gidp("QEPSRevenueConsensusEstimateRoute", symbol))
    except Exception as e:
        logger.warning("fetch_raw_eps_route %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的EPS路徑資料"}


async def fetch_raw_margin_route(symbol: str) -> dict:
    """未來五季毛利率/營益率預估路徑（QMargingsConsensusEstimateRoute，gidp）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_gidp("QMargingsConsensusEstimateRoute", symbol))
    except Exception as e:
        logger.warning("fetch_raw_margin_route %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的利潤率路徑資料"}


async def fetch_raw_rating_trend(symbol: str) -> dict:
    """分析師評等佔比趨勢（AnalystRatingChangeTrend，gidp）。回原始 data。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        inner = _unwrap(await _get_gidp("AnalystRatingChangeTrend", symbol))
    except Exception as e:
        logger.warning("fetch_raw_rating_trend %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return inner if isinstance(inner, dict) else {"error": f"查無 {symbol} 的評等趨勢資料"}


# ══════════════════════════════════════════════════════════════════════════
# raw fetchers — jwt domain（Bearer access_token）
# ══════════════════════════════════════════════════════════════════════════


async def _request_with_auth(url: str, params: dict | None = None) -> dict | None:
    """JWT 通用 GET + 401 自動 refresh/re-login。"""
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
            if await _auth.refresh():
                headers["Authorization"] = f"Bearer {_auth.access_token}"
                r = await client.get(url, headers=headers, params=params)
            elif await _auth.login():
                headers["Authorization"] = f"Bearer {_auth.access_token}"
                r = await client.get(url, headers=headers, params=params)
            else:
                return None
        return r.json() if r.status_code == 200 else None


async def fetch_raw_report_summaries(
    symbol: str | None = None, limit: int = 50, offset: int = 0
) -> dict:
    """研究報告摘要（report-summaries，jwt）。回原始 json。

    帶 symbol → 該股報告；不帶 symbol → 全站最新 limit/offset（推播監控用）。
    合併原 get_reports（單股）與 list_latest_reports（全站）為單一帶參 fetcher。
    """
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    params: dict = {"limit": limit, "offset": offset}
    if symbol:
        params["stock"] = symbol.strip().upper()
    try:
        payload = await _request_with_auth(f"{BASE_URL}/api/report-summaries", params)
    except Exception as e:
        logger.warning("fetch_raw_report_summaries: %s", e)
        return {"error": f"取數失敗：{e}"}
    return payload if isinstance(payload, dict) else {"error": "查無研究報告資料"}


async def fetch_raw_completion(symbol: str, prompt: str) -> dict:
    """AI 分析（/completions，jwt；呼叫外部 AI，歸 raw）。回原始 json。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
    try:
        payload = await _request_with_auth(
            f"{BASE_URL}/completions", {"prompt": prompt, "stock": symbol}
        )
    except Exception as e:
        logger.warning("fetch_raw_completion %s: %s", symbol, e)
        return {"error": f"取數失敗：{e}"}
    return payload if isinstance(payload, dict) else {"error": f"UAnalyze 無法取得 {symbol} 的分析"}


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


async def fetch_raw_ai_chat(symbol: str, question: str, kb: str = DEFAULT_KB) -> dict:
    """AI 知識庫問答（/chat/{kb}，jwt SSE；呼叫外部 AI，歸 raw）。

    回 {"symbol","question","knowledge_base","chunks":[...],"answer":原始串接}。
    <think> 標記的濾除交給消費者（analysis/Agent）。
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    if not (question or "").strip():
        return {"error": "請輸入問題"}
    api_name = UA_KNOWLEDGE_BASES.get(
        kb, kb if kb.startswith("ua_ai_insight_") else UA_KNOWLEDGE_BASES[DEFAULT_KB]
    )
    token = await _auth.ensure_token()
    if not token:
        return dict(ERR_NO_LOGIN)

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
                        async for chunk in _collect_chat(resp2):
                            chunks.append(chunk)
                elif resp.status_code == 200:
                    async for chunk in _collect_chat(resp):
                        chunks.append(chunk)
                else:
                    return {"error": f"UAnalyze 問答失敗（HTTP {resp.status_code}）"}
    except Exception as e:
        logger.warning("fetch_raw_ai_chat %s: %s", symbol, e)
        return {"error": f"UAnalyze 問答發生錯誤：{e}"}

    answer = "".join(chunks)
    if not answer:
        return {"error": f"UAnalyze 未回傳 {symbol} 的問答內容"}
    return {
        "symbol": symbol,
        "question": question,
        "knowledge_base": api_name,
        "chunks": chunks,
        "answer": answer,
    }


# ══════════════════════════════════════════════════════════════════════════
# raw fetcher — 批次雷達（cronjob company_keywords，特殊認證：僅 Origin/Referer）
# ══════════════════════════════════════════════════════════════════════════


async def fetch_raw_company_keywords(keyword: str, types: str = DEFAULT_RADAR_TYPES) -> dict:
    """批次雷達（company_keywords/<types>，POST multipart；不帶 token）。回原始 json。

    ⚠️ 回傳可能數十 MB（全站多類資料）。落地/摘要是消費者（analysis）的事，
    raw 層只負責抓回原始 payload。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"error": "請輸入查詢關鍵字"}
    if not await _auth.ensure_token():
        return dict(ERR_NO_LOGIN)
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
        logger.warning("fetch_raw_company_keywords %s: %s", keyword, e)
        return {"error": f"批次雷達發生錯誤：{e}"}
    if r.status_code != 200:
        return {"error": f"批次雷達失敗（HTTP {r.status_code}）"}
    try:
        payload = r.json()
    except Exception:
        return {"error": "批次雷達回傳非 JSON"}
    return payload if isinstance(payload, dict) else {"error": "批次雷達回傳格式異常"}


# ── CLI：python tools/raw/uanalyze.py <fetcher> <args...> ──────────────────
# 薄 CLI，主要供 Agent 直接叫某個 raw fetcher。fetcher 名 = 去掉 fetch_raw_ 前綴。

_CLI_FETCHERS = {
    "historical_per": fetch_raw_historical_per,
    "historical_pbr": fetch_raw_historical_pbr,
    "pe_band": fetch_raw_pe_band,
    "per_share_value": fetch_raw_per_share_value,
    "stock_comparison_pool": fetch_raw_stock_comparison_pool,
    "institutional_net": fetch_raw_institutional_net,
    "profit_margins": fetch_raw_profit_margins,
    "cash_flow_trend": fetch_raw_cash_flow_trend,
    "cash_dividend_payout": fetch_raw_cash_dividend_payout,
    "margin_balance": fetch_raw_margin_balance,
    "short_interest": fetch_raw_short_interest,
    "major_investors_holdings": fetch_raw_major_investors_holdings,
    "shareholders_stats": fetch_raw_shareholders_stats,
    "transcript_detail": fetch_raw_transcript_detail,
    "eps_revenue_consensus": fetch_raw_eps_revenue_consensus,
    "revenue_tracking": fetch_raw_revenue_tracking,
    "eps_tracking": fetch_raw_eps_tracking,
    "broker_eps_table": fetch_raw_broker_eps_table,
    "order_visibility": fetch_raw_order_visibility,
    "web_stock_info": fetch_raw_web_stock_info,
    "smart_estimate": fetch_raw_smart_estimate,
    "eps_route": fetch_raw_eps_route,
    "margin_route": fetch_raw_margin_route,
    "rating_trend": fetch_raw_rating_trend,
    "report_summaries": fetch_raw_report_summaries,
    "completion": fetch_raw_completion,
    "ai_chat": fetch_raw_ai_chat,
    "company_keywords": fetch_raw_company_keywords,
}


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in _CLI_FETCHERS:
        print(json.dumps(
            {"error": f"用法: python tools/raw/uanalyze.py <fetcher> <args...>；"
                      f"可用: {', '.join(sorted(_CLI_FETCHERS))}"},
            ensure_ascii=False,
        ))
        sys.exit(1)
    fn = _CLI_FETCHERS[args[0]]
    fn_args = args[1:]
    result = asyncio.run(fn(*fn_args))
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(1 if isinstance(result, dict) and "error" in result else 0)
