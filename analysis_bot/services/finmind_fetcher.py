import asyncio
import aiohttp
import pandas as pd
from typing import List, Dict, Tuple, Optional
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from ..config import get_settings

settings = get_settings()

FETCH_URL = "https://api.finmindtrade.com/api/v4/data"
USELIMIT_URL = "https://api.web.finmindtrade.com/v2/user_info"

class FinMindFetcher:
    """Service to fetch data from FinMind API with token rotation."""
    
    def __init__(self, tokens: List[str] = None):
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

    async def _fetch_data(self, session: aiohttp.ClientSession, dataset: str, params: Optional[Dict] = None) -> pd.DataFrame:
        if not self.tokens:
            print("Warning: No FinMind tokens provided. API calls may fail or be limited.")
            token = ""
        else:
            token = self.tokens[self.current_token_idx]

        params = params or {}
        params.update({
            "dataset": dataset,
            "token": token
        })

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_fixed(5),
            retry=retry_if_exception_type((aiohttp.ClientError, OverflowError)),
        )
        async def _request():
            async with session.get(FETCH_URL, params=params, ssl=False) as resp:
                if resp.status == 402: # Payment/Limit required
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
            print(f"FinMind fetch error for {dataset}: {e}")
            return pd.DataFrame()

    async def get_per_pbr(self, session: aiohttp.ClientSession, stock_id: str, start_date: str) -> Tuple[List[float], List[float]]:
        df = await self._fetch_data(
            session, "TaiwanStockPER", 
            {"data_id": stock_id, "start_date": start_date}
        )
        if df.empty or "PER" not in df or "PBR" not in df:
            print(f"DEBUG: get_per_pbr failed for {stock_id}. Empty: {df.empty}, Columns: {df.columns if not df.empty else 'N/A'}")
            return [], []
        
        return df["PER"].astype(float).tolist(), df["PBR"].astype(float).tolist()

    async def get_eps(self, session: aiohttp.ClientSession, stock_id: str, start_date: str) -> List[float]:
        df = await self._fetch_data(
            session, "TaiwanStockFinancialStatements", 
            {"data_id": stock_id, "start_date": start_date}
        )
        if df.empty:
             return []
        # Filter for EPS
        # Legacy: df[df["type"] == "EPS"]["value"]
        if "type" in df and "value" in df:
             return df[df["type"] == "EPS"]["value"].astype(float).tolist()
        return []

    async def get_stock_info(self, session: aiohttp.ClientSession, stock_id: str) -> Dict[str, str]:
        """Fetch basic stock info (Name, Sector) from FinMind."""
        df = await self._fetch_data(
            session, "TaiwanStockInfo", 
            {"data_id": stock_id}
        )
        if df.empty:
            return {}
        
        # DataFrame columns: industry_category, stock_id, stock_name, type, date
        row = df.iloc[0]
        return {
            "name": row.get("stock_name", ""),
            "sector": row.get("industry_category", ""),
            "exchange": "TWSE" if row.get("type") == "twse" else "TPEX" 
        }
