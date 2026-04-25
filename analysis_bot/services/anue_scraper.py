import asyncio
import logging
from datetime import datetime
from urllib.parse import unquote

import aiohttp
from bs4 import BeautifulSoup

# Using simple logger for now
logger = logging.getLogger(__name__)

CNYEA_URL_PART = "news.cnyes.com/news/id"
CNYES_EPS_API = "https://marketinfo.api.cnyes.com/mi/api/v1/financialIndicator/estimateProfit/TWS:{stock_id}:STOCK?type=eps"


class AnueScraper:
    """Service to scrape estimated EPS and Target Price from Anue (Cnyes)."""

    def __init__(self, level: int = 4):
        self.level = level  # legacy parameter for EPS table row index?

    # ── CNYES JSON API (primary) ─────────────────────────────────────────

    async def _fetch_eps_from_api(
        self, session: aiohttp.ClientSession, stock_id: str
    ) -> dict | None:
        """Fetch EPS estimates from CNYES marketinfo API (FactSet data)."""
        url = CNYES_EPS_API.format(stock_id=stock_id)
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json(content_type=None)

            items = payload.get("data")
            if not items:
                return None

            # Find current year and next year entries
            now = datetime.now()
            current_year = now.year
            by_year = {it["financialYear"]: it for it in items if isinstance(it, dict)}

            cur = by_year.get(current_year)
            nxt = by_year.get(current_year + 1)
            if not cur:
                return None

            this_eps = cur.get("feMedian") or cur.get("feMean")
            if this_eps is None:
                return None

            next_eps = (nxt.get("feMedian") or nxt.get("feMean")) if nxt else this_eps
            tm_yday = float(now.timetuple().tm_yday)
            weighted_eps = ((366 - tm_yday) / 366) * this_eps + (tm_yday / 366) * next_eps

            return {
                "est_price": None,
                "est_eps": round(weighted_eps, 2),
                "url": f"https://invest.cnyes.com/twstock/{stock_id}",
                "date": (cur.get("rateDate") or now.isoformat()),
            }
        except Exception as e:
            logger.debug("CNYES EPS API failed for %s: %s", stock_id, e)
            return None

    async def _fetch_all_from_api(
        self, session: aiohttp.ClientSession, stock_id: str
    ) -> list[dict]:
        """Fetch per-year EPS snapshots from CNYES API for momentum tracking."""
        url = CNYES_EPS_API.format(stock_id=stock_id)
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                payload = await resp.json(content_type=None)

            items = payload.get("data")
            if not items:
                return []

            results = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                eps = it.get("feMedian") or it.get("feMean")
                if eps is None:
                    continue
                results.append({
                    "est_price": None,
                    "est_eps": round(eps, 2),
                    "url": f"https://invest.cnyes.com/twstock/{stock_id}",
                    "date": it.get("rateDate") or datetime.now().isoformat(),
                })

            results.sort(key=lambda x: x["date"], reverse=True)
            return results
        except Exception as e:
            logger.debug("CNYES EPS API (all) failed for %s: %s", stock_id, e)
            return []

    # ── Public interface ─────────────────────────────────────────────────

    async def fetch_estimated_data(
        self, session: aiohttp.ClientSession, stock_id: str, stock_name: str
    ) -> dict | None:
        """
        Attempts to find estimate report for the stock.
        Returns dict with {est_price, est_eps, date, url} or None.
        Primary: CNYES JSON API. Fallback: Yahoo search + HTML scraping.
        """
        # Primary: CNYES API
        result = await self._fetch_eps_from_api(session, stock_id)
        if result and result.get("est_eps"):
            logger.debug("EPS from CNYES API for %s: %s", stock_id, result["est_eps"])
            return result

        # Fallback: Yahoo search + HTML scraping
        return await self._fetch_eps_from_search(session, stock_id, stock_name)

    async def _fetch_eps_from_search(
        self, session: aiohttp.ClientSession, stock_id: str, stock_name: str
    ) -> dict | None:
        """Fallback: search Yahoo for CNYES FactSet articles and scrape EPS table."""
        search_query = (
            f"鉅亨速報 - Factset 最新調查：{stock_name}({stock_id}-TW)EPS預估+site:news.cnyes.com"
        )

        # 1. Search for article URL
        # We try Google or Yahoo. Legacy preferred Yahoo due to anti-bot?
        # Let's try to simulate what legacy did.
        url = f"https://tw.search.yahoo.com/search?p={search_query}"

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            logger.debug("Searching URL: %s", url)
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.debug("Search failed with status %s", resp.status)
                    return None
                text = await resp.text()
                soup = BeautifulSoup(text, "html.parser")

            # Parse search results
            target_urls = []

            for link in soup.find_all("a"):
                href = link.get("href")
                if href:
                    # Filter for actual news ID pattern to avoid Yahoo junk
                    # Yahoo search results for external sites usually go through a redirect or are direct
                    # We specifically want "news.cnyes.com/news/id"

                    clean_link = href
                    if "RU=" in href:
                        try:
                            clean_link = unquote(href.split("RU=")[1].split("/RK=")[0])
                        except (IndexError, ValueError) as e:
                            logger.debug(f"URL decode failed for {href}: {e}")

                    if CNYEA_URL_PART in clean_link:
                        target_urls.append(clean_link)

            # Remove duplicates while preserving order
            target_urls = list(dict.fromkeys(target_urls))

            logger.debug("Filtered target_urls: %s", target_urls)
            if not target_urls:
                return None

            # 2. Process articles
            tm_yday = float(datetime.now().timetuple().tm_yday)

            candidates = []

            results = await asyncio.gather(
                *[self._process_article(session, url, stock_id, tm_yday) for url in target_urls],
                return_exceptions=True,
            )
            candidates = [r for r in results if r and not isinstance(r, BaseException)]

            if not candidates:
                return None

            # Sort by date descending (latest first)
            # Ensure 'date' is a datetime object
            candidates.sort(key=lambda x: x["date"], reverse=True)

            logger.debug(
                "Found %d candidates. Choosing latest: %s - %s",
                len(candidates),
                candidates[0]["date"],
                candidates[0]["url"],
            )
            return candidates[0]

        except Exception as e:
            logger.error(f"Anue scrape error: {e}")
            logger.debug("Exception in Anue scrape: %s", e)

        return None

    async def fetch_all_estimates(
        self, session: aiohttp.ClientSession, stock_id: str, stock_name: str
    ) -> list[dict]:
        """
        Fetch ALL available FactSet EPS estimate articles (not just the latest).
        Used by EpsMomentumService to build historical EPS timeline.
        Primary: CNYES API (one snapshot per year). Fallback: Yahoo search + HTML scraping.
        Returns list of dicts sorted by date descending.
        """
        # Primary: CNYES API — returns per-year estimates as individual snapshots
        api_result = await self._fetch_all_from_api(session, stock_id)
        if api_result:
            return api_result

        # Fallback: Yahoo search + HTML scraping
        search_query = (
            f"鉅亨速報 - Factset 最新調查：{stock_name}({stock_id}-TW)EPS預估+site:news.cnyes.com"
        )
        url = f"https://tw.search.yahoo.com/search?p={search_query}"

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()
                soup = BeautifulSoup(text, "html.parser")

            target_urls = []
            for link in soup.find_all("a"):
                href = link.get("href")
                if href:
                    clean_link = href
                    if "RU=" in href:
                        try:
                            clean_link = unquote(href.split("RU=")[1].split("/RK=")[0])
                        except (IndexError, ValueError) as e:
                            logger.debug(f"URL decode failed for {href}: {e}")
                    if CNYEA_URL_PART in clean_link:
                        target_urls.append(clean_link)

            target_urls = list(dict.fromkeys(target_urls))
            if not target_urls:
                return []

            tm_yday = float(datetime.now().timetuple().tm_yday)
            results = await asyncio.gather(
                *[self._process_article(session, url, stock_id, tm_yday) for url in target_urls],
                return_exceptions=True,
            )
            candidates = [r for r in results if r and not isinstance(r, BaseException)]

            candidates.sort(key=lambda x: x["date"], reverse=True)
            return candidates

        except Exception as e:
            logger.error(f"Anue fetch_all_estimates error: {e}")

        return []

    async def _process_article(self, session, url, stock_id, tm_yday) -> dict | None:
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
                soup = BeautifulSoup(text, "html.parser")

            import json as _json

            # Logic ported from legacy __process_page
            # 1. Check title — try __NEXT_DATA__ first, then DOM selectors
            title_text = ""

            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                try:
                    data = _json.loads(nd.string)
                    props = data.get("props", {}).get("pageProps", {})
                    detail = props.get("newsDetail") or props.get("article") or {}
                    title_text = detail.get("content", "") or detail.get("title", "")
                except (ValueError, KeyError):
                    pass

            if not title_text:
                for sel_fn in [
                    lambda s: s.find(id="article-container"),
                    lambda s: s.select_one("div[itemprop='articleBody']"),
                    lambda s: s.find("article"),
                    lambda s: s.find("h1"),
                ]:
                    el = sel_fn(soup)
                    if el:
                        title_text = el.get_text()
                        break
            if not title_text:
                return None

            # Check if title strictly matches format "Name(ID-TW)..."
            if str(stock_id) not in title_text:
                return None

            # 2. Extract Target Price
            # "預估目標價為xxx元"
            est_price = None
            if "預估目標價為" in title_text:
                try:
                    est_price = float(title_text.split("預估目標價為")[1].split("元")[0])
                except (ValueError, IndexError):
                    pass

            # 3. Extract EPS Table
            weighted_eps = None
            # Find EPS table: look for table containing "預估值"
            table = None
            for t in soup.find_all("table"):
                if "預估值" in t.get_text():
                    table = t
                    break
            if table:
                rows = table.find_all("tr")
                if len(rows) > 1:
                    headers = [td.get_text(strip=True) for td in rows[0].find_all("td")]
                    if headers and any("預估值" in h for h in headers):
                        target_row_idx = self.level
                        if target_row_idx < len(rows):
                            row = rows[target_row_idx]
                            cols = [td.get_text(strip=True) for td in row.find_all("td")]
                            if not cols or len(cols) < len(headers):
                                cols = []  # skip malformed row

                            current_year = str(datetime.now().year)
                            for idx, h in enumerate(headers):
                                if current_year in h and idx < len(cols):
                                    try:
                                        this_year_eps = float(cols[idx].split("(")[0])
                                        next_year_eps = this_year_eps
                                        if idx + 1 < len(cols):
                                            try:
                                                next_year_eps = float(cols[idx + 1].split("(")[0])
                                            except (ValueError, IndexError):
                                                pass

                                        weighted_eps = ((366 - tm_yday) / 366) * this_year_eps + (
                                            tm_yday / 366
                                        ) * next_year_eps
                                    except (ValueError, IndexError):
                                        pass
                                    break

            # 4. Extract Date
            article_date = None

            # Try meta tag first
            meta_date = soup.find("meta", property="article:published_time")
            if meta_date and meta_date.get("content"):
                try:
                    # Try simplified date parse if standard fails
                    # Anue meta sometimes has Chinese like "2024/1/19 下午5:11:18"
                    article_date = datetime.fromisoformat(meta_date["content"])
                except (ValueError, TypeError):
                    pass

            # Fallback to time tag if meta failed
            if not article_date:
                time_tag = soup.find("time")
                if time_tag and time_tag.get("datetime"):
                    try:
                        # "2024-01-19T09:11:18.000Z" - Python 3.13 handles Z
                        article_date = datetime.fromisoformat(time_tag["datetime"])
                    except (ValueError, TypeError):
                        pass

            # Final fallback to now if everything failed
            if not article_date:
                article_date = datetime.now()

            if est_price or weighted_eps:
                return {
                    "est_price": est_price,
                    "est_eps": weighted_eps,  # Weighted
                    "url": url,
                    "date": article_date.isoformat() if article_date else None,
                }

        except Exception as e:
            logger.debug("Article parse failed for %s: %s", url, e)

        return None
