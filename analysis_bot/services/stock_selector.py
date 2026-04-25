import asyncio
import logging
import re
from collections import Counter
import pandas as pd
from bs4 import BeautifulSoup
from natsort import natsorted
from sqlmodel import Session, select

from .http import create_session

from ..database import engine
from ..models.config import SystemConfig

logger = logging.getLogger(__name__)

ETF_BASE_URL = "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={}.TW"
ETF_RANK_URL = "https://www.moneydj.com/ETF/X/Rank/Rank0007.xdjhtm?eRank=irr&eOrd=t800652&eMid=TW&eArea=0&eTarget=22&eCoin=AX000010&eTab=1"
INVESTOR_URL = "https://histock.tw/stock/three.aspx?s={}"
INVESTOR_TYPES = {"foreign": "a", "investment_trust": "b", "dealers": "c"}


class StockSelector:
    """Service to fetch dynamic stock lists (ETF components, Institutional buying, etc.)."""

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.99 Safari/537.36"
        }

    async def fetch_webpage(self, session, url: str) -> BeautifulSoup:
        try:
            is_moneydj = "moneydj.com" in url
            async with session.get(
                url, headers=self.headers, timeout=10, ssl=(not is_moneydj)
            ) as response:
                response.raise_for_status()
                text = await response.text(encoding="utf-8")
                return BeautifulSoup(text, "html.parser")
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def is_ordinary_stock(self, stock: str) -> bool:
        if not stock or len(stock) < 4:
            return False
        if not stock.isdigit():
            return False
        return stock[0] in "123456789"

    async def parse_etf_rank_data(self, session):
        soup = await self.fetch_webpage(session, ETF_RANK_URL)
        if not soup:
            return pd.DataFrame()

        table = soup.find("table", id="oMainTable")  # Changed myid to id or attrs
        if not table:
            # Try finding by attribute if id fails
            table = soup.find("table", attrs={"myid": "oMainTable"})

        if not table:
            return pd.DataFrame()

        headers = []
        thead = table.find("thead")
        if thead:
            header_row = thead.find_all("tr")[0]
            for th in header_row.find_all("th"):
                headers.append(th.text.strip())

        rows = []
        tbody = table.find("tbody")
        if tbody:
            for tr in tbody.find_all("tr"):
                row = []
                for td in tr.find_all("td"):
                    text = td.text.strip()
                    if td.find("a"):
                        if td.find("a").get("etfid"):
                            text = td.find("a")["etfid"]
                        else:
                            text = td.find("a").text.strip()
                    row.append(text)
                rows.append(row)

        df = pd.DataFrame(rows)
        # Assuming structure matches observation (headers might be mismatched if dynamic)
        # Simplified based on old code logic
        if not df.empty and df.shape[1] >= 12:
            # Drop check box and image columns if present (indices 0, 1)
            # But here headers might be clean. Let's rely on column count.
            # Old code dropped 0 and 1.
            df = df.iloc[:, 2:]

            new_cols = [
                "Rank",
                "ETF_Code",
                "ETF_Name",
                "Date",
                "Currency",
                "Annualized_Return_Since_Inception",
                "1D_Return",
                "1W_Return",
                "YTD_Return",
                "1M_Return",
                "3M_Return",
                "1Y_Return",
            ]
            if df.shape[1] == len(new_cols):
                df.columns = new_cols

                numeric_columns = new_cols[5:]
                for col in numeric_columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    async def fetch_etf_constituents(self, session, etf_id: str) -> list[str]:
        soup = await self.fetch_webpage(session, ETF_BASE_URL.format(etf_id))
        if not soup:
            return []

        constituents = set()
        for a in soup.select("td.col05 a"):
            href = a.get("href")
            if href:
                match = re.search(r"etfid=(\d+)\.", href)
                if match:
                    constituents.add(match.group(1))

        return natsorted(list(constituents))

    async def fetch_investor_stocks(self, session, investor_type: str) -> list[str]:
        soup = await self.fetch_webpage(session, INVESTOR_URL.format(investor_type))
        if not soup:
            return []

        stocks = []
        seen = set()

        # Primary: look for links with stock code in href (e.g. /stock/1234)
        for a in soup.find_all("a", href=True):
            m = re.search(r"/stock/(\d{4,5})(?:\b|$)", a["href"])
            if m:
                code = m.group(1)
                if self.is_ordinary_stock(code) and code not in seen:
                    stocks.append(code)
                    seen.add(code)

        # Fallback: table rows with stock code in first cell
        if not stocks:
            for tr in soup.find_all("tr"):
                tds = tr.find_all("td")
                if not tds:
                    continue
                code = tds[0].get_text(strip=True)
                if self.is_ordinary_stock(code) and code not in seen:
                    stocks.append(code)
                    seen.add(code)

        return stocks

    async def fetch_institutional_top50(self, session=None) -> list[str]:
        """Fetch top 50 stocks from 3 institutional investors."""
        should_close = False
        if not session:
            session = create_session()
            should_close = True

        try:
            tasks = [
                self.fetch_investor_stocks(session, i_type) for i_type in INVESTOR_TYPES.values()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            all_stocks = set()
            for res in results:
                if isinstance(res, list):
                    all_stocks.update(res)

            return natsorted(list(all_stocks))
        finally:
            if should_close:
                await session.close()

    async def fetch_etf_rank_stocks(self, session=None) -> list[str]:
        """Fetch popular stocks from top performing ETFs."""
        should_close = False
        if not session:
            session = create_session()
            should_close = True

        try:
            df = await self.parse_etf_rank_data(session)
            if df.empty:
                return []

            # Filter: 1Y Return > 10%
            if "1Y_Return" in df.columns:
                df_filtered = df[df["1Y_Return"] > 10]
            else:
                df_filtered = pd.DataFrame()  # fail safe

            if df_filtered.empty:
                return []

            tasks = []
            for _, row in df_filtered.iterrows():
                etf_id = str(row["ETF_Code"])
                tasks.append(self.fetch_etf_constituents(session, etf_id))

            results = await asyncio.gather(*tasks)
            all_constituents = [c for sublist in results for c in sublist]
            counts = Counter(all_constituents)

            # Select stocks appearing in at least 10 top ETFs
            stocks = [code for code, count in counts.most_common() if count >= 10]

            return natsorted(stocks)
        finally:
            if should_close:
                await session.close()

    def _parse_list(self, config_str: str) -> list[str]:
        if not config_str:
            return []
        # Support space or comma
        return [s.strip().upper() for s in re.split(r"[ ,]+", config_str) if s.strip()]

    async def get_invest_anchors(self, session=None) -> list[str]:
        """Fetch invest anchors from SystemConfig."""
        with Session(engine) as db_session:
            config = db_session.exec(
                select(SystemConfig).where(SystemConfig.key == "investanchors")
            ).first()
            return self._parse_list(config.value) if config else []

    async def get_user_choice(self, session=None) -> list[str]:
        with Session(engine) as db_session:
            config = db_session.exec(
                select(SystemConfig).where(SystemConfig.key == "user_choice")
            ).first()
            return self._parse_list(config.value) if config else []

    async def get_target_etfs(self, session=None) -> list[str]:
        """Fetch target ETFs from SystemConfig."""
        with Session(engine) as db_session:
            config = db_session.exec(
                select(SystemConfig).where(SystemConfig.key == "target_etfs")
            ).first()
            return self._parse_list(config.value) if config else []
