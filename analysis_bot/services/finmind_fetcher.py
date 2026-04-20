import logging

import aiohttp
import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

FETCH_URL = "https://api.finmindtrade.com/api/v4/data"
TICK_SNAPSHOT_URL = "https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot"
USELIMIT_URL = "https://api.web.finmindtrade.com/v2/user_info"


class FinMindFetcher:
    """Service to fetch data from FinMind API with token rotation."""

    def __init__(self, tokens: list[str] = None):
        # Allow passing tokens or load from settings
        self.tokens = tokens or settings.FINMIND_TOKENS or []
        self.current_token_idx = 0
        self.api_request_limit = 600

    async def _rotate_token(self, session: aiohttp.ClientSession):
        if not self.tokens:
            return

        self.current_token_idx = (self.current_token_idx + 1) % len(self.tokens)

        # Simple limit check logic ported from legacy
        # In a real high-throughput app, we might want a shared state store (Redis)
        # but for this local bot, in-memory is fine.

        # Omitted complexity: checking usage limit via API for every rotation
        # to keep it fast, unless explicitly needed. Legacy did check it.
        pass

    async def _fetch_data(
        self, session: aiohttp.ClientSession, dataset: str, params: dict | None = None
    ) -> pd.DataFrame:
        if not self.tokens:
            logger.warning("No FinMind tokens provided. API calls may fail or be limited.")
            token = ""
        else:
            token = self.tokens[self.current_token_idx]

        params = params or {}
        params.update({"dataset": dataset, "token": token})

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_fixed(5),
            retry=retry_if_exception_type((aiohttp.ClientError, OverflowError)),
        )
        async def _request():
            async with session.get(FETCH_URL, params=params) as resp:
                if resp.status == 402:  # Payment/Limit required
                    # Trigger rotation
                    await self._rotate_token(session)
                    params["token"] = self.tokens[self.current_token_idx]
                    raise OverflowError("Token limit reached")
                resp.raise_for_status()
                return await resp.json()

        try:
            data = await _request()
            if "data" in data:
                return pd.DataFrame(data["data"])
            return pd.DataFrame()
        except Exception as e:
            logger.warning("FinMind fetch error for %s: %s", dataset, e)
            return pd.DataFrame()

    async def get_per_pbr(
        self, session: aiohttp.ClientSession, stock_id: str, start_date: str
    ) -> tuple[list[float], list[float]]:
        df = await self._fetch_data(
            session, "TaiwanStockPER", {"data_id": stock_id, "start_date": start_date}
        )
        if df.empty or "PER" not in df or "PBR" not in df:
            logger.debug(
                "get_per_pbr failed for %s. Empty: %s, Columns: %s",
                stock_id,
                df.empty,
                df.columns if not df.empty else "N/A",
            )
            return [], []

        return df["PER"].astype(float).tolist(), df["PBR"].astype(float).tolist()

    async def get_eps(
        self, session: aiohttp.ClientSession, stock_id: str, start_date: str
    ) -> list[float]:
        df = await self._fetch_data(
            session,
            "TaiwanStockFinancialStatements",
            {"data_id": stock_id, "start_date": start_date},
        )
        if df.empty:
            return []
        # Filter for EPS
        # Legacy: df[df["type"] == "EPS"]["value"]
        if "type" in df and "value" in df:
            return df[df["type"] == "EPS"]["value"].astype(float).tolist()
        return []

    async def get_tick_snapshot(self, session: aiohttp.ClientSession, stock_id: str) -> dict | None:
        """
        台股即時報價（約 10 秒更新）。僅限 Sponsor 會員。
        成功回傳 dict 含 close, change_price, change_rate, date 等；失敗回傳 None。
        """
        if not self.tokens:
            return None
        token = self.tokens[self.current_token_idx]
        headers = {"Authorization": f"Bearer {token}"}
        params = {"data_id": stock_id}
        try:
            async with session.get(TICK_SNAPSHOT_URL, headers=headers, params=params) as resp:
                if resp.status in (402, 403):
                    logger.debug("FinMind tick snapshot requires Sponsor: %s", resp.status)
                    return None
                resp.raise_for_status()
                data = await resp.json()
                rows = data.get("data", [])
                if not rows:
                    return None
                row = rows[0]
                close = row.get("close")
                if close is None:
                    return None
                return {
                    "close": float(close),
                    "change_price": row.get("change_price"),
                    "change_rate": row.get("change_rate"),
                    "date": row.get("date"),
                    "buy_price": row.get("buy_price"),
                    "sell_price": row.get("sell_price"),
                }
        except Exception as e:
            logger.debug("FinMind tick snapshot error: %s", e)
            return None

    async def get_stock_info(self, session: aiohttp.ClientSession, stock_id: str) -> dict[str, str]:
        """Fetch basic stock info (Name, Sector) from FinMind."""
        df = await self._fetch_data(session, "TaiwanStockInfo", {"data_id": stock_id})
        if df.empty:
            return {}

        # DataFrame columns: industry_category, stock_id, stock_name, type, date
        row = df.iloc[0]
        return {
            "name": row.get("stock_name", ""),
            "sector": row.get("industry_category", ""),
            "exchange": "TWSE" if row.get("type") == "twse" else "TPEX",
        }
