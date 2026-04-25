"""
鉅亨網台股即時報價爬蟲。

來源：invest.cnyes.com/twstock/{stock_id}
台股與外匯為即時資訊（頁面聲明）。
"""

import logging
import re

import aiohttp
from bs4 import BeautifulSoup

from .http import create_session, http_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://invest.cnyes.com/twstock"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


@http_retry
async def fetch_tw_quote(
    stock_id: str,
    session: aiohttp.ClientSession | None = None,
) -> dict | None:
    """
    從鉅亨網抓取台股即時報價。

    Args:
        stock_id: 股票代碼（4 碼或 5 碼）
        session: 可選的 aiohttp session

    Returns:
        {"name": str, "price": float, "change": float, "change_pct": float} 或 None
    """
    url = f"{BASE_URL}/{stock_id}"
    own_session = session is None

    if own_session:
        timeout = aiohttp.ClientTimeout(total=15)
        session = create_session(headers=DEFAULT_HEADERS, timeout=timeout)

    try:
        async with session.get(url, ssl=True) as resp:
            if resp.status != 200:
                logger.debug("CNYES quote %s: HTTP %s", stock_id, resp.status)
                return None
            text = await resp.text()
    except aiohttp.ClientError as e:
        logger.debug("CNYES quote %s: %s", stock_id, e)
        return None
    finally:
        if own_session:
            await session.close()

    return _parse_quote_page(text, stock_id)


def _parse_quote_page(html: str, stock_id: str) -> dict | None:
    """解析鉅亨個股頁面，提取股名、價格、漲跌。"""
    soup = BeautifulSoup(html, "html.parser")

    # Try __NEXT_DATA__ first (most reliable for Next.js SPA)
    import json as _json

    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        try:
            data = _json.loads(nd.string)
            props = data.get("props", {}).get("pageProps", {})
            quote = props.get("quote") or props.get("stock") or {}
            if isinstance(quote, dict):
                q_name = quote.get("name") or quote.get("stkName") or stock_id
                q_price = quote.get("price") or quote.get("lastPrice")
                q_change = quote.get("change") or quote.get("priceChange")
                q_pct = quote.get("changePercent") or quote.get("priceChangePercent")
                if q_price is not None:
                    try:
                        return {
                            "name": str(q_name),
                            "price": float(q_price),
                            "change": float(q_change) if q_change is not None else None,
                            "change_pct": float(q_pct) if q_pct is not None else None,
                        }
                    except (ValueError, TypeError):
                        pass
        except (ValueError, KeyError):
            pass

    # Fallback: heuristic h1/h2/h3 parsing
    name = None
    for h in soup.find_all(["h1", "h2"]):
        t = (h.get_text() or "").strip()
        if stock_id in t:
            name = re.sub(r"\d{4,5}.*$", "", t).strip() or t
            break
    if not name:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content") and stock_id in og_title["content"]:
            name = re.sub(r"\d{4,5}.*$", "", og_title["content"]).strip() or stock_id
    if not name:
        name = stock_id

    # 價格與漲跌：股名 h2 之後的 h3（價格）及緊鄰文字（漲跌）
    price = None
    price_h3 = None

    def _has_stock_id(tag):
        return tag.name in ("h1", "h2") and stock_id in (tag.get_text() or "")

    stock_h2 = soup.find(_has_stock_id)
    if stock_h2:
        for elem in stock_h2.find_all_next(["h3", "h1", "h2"], limit=20):
            if elem.name == "h3":
                t = (elem.get_text() or "").strip().replace(",", "")
                m = re.match(r"^(\d+\.?\d*)$", t)
                if m:
                    try:
                        p = float(m.group(1))
                        if 0.1 <= p <= 999_999:
                            price = p
                            price_h3 = elem
                            break
                    except ValueError:
                        pass
            elif elem.name in ("h1", "h2"):
                break

    if price is None:
        for h3 in soup.find_all("h3"):
            t = (h3.get_text() or "").strip().replace(",", "")
            m = re.match(r"^(\d+\.?\d*)$", t)
            if m:
                try:
                    p = float(m.group(1))
                    if 1 <= p <= 999_999:
                        price = p
                        price_h3 = h3
                        break
                except ValueError:
                    pass

    if price is None:
        logger.debug("CNYES parse: no price for %s", stock_id)
        return None

    # 漲跌：從 h3 父層文字找 -195.00-1.62%（排除 SVG path 的 %20 等）
    change = None
    change_pct = None
    change_pattern = re.compile(r"([+-]\d+\.?\d*)\s*([+-]\d+\.?\d*)\s*%(?!\d)")
    if price_h3:
        parent = price_h3.parent
        if parent:
            parent_text = parent.get_text(separator=" ", strip=True)
            change_match = change_pattern.search(parent_text)
            if change_match:
                try:
                    change = float(change_match.group(1))
                    change_pct = float(change_match.group(2).rstrip("%"))
                except ValueError:
                    pass
    if change is None:
        change_match = change_pattern.search(html)
        if change_match:
            try:
                change = float(change_match.group(1))
                change_pct = float(change_match.group(2).rstrip("%"))
            except ValueError:
                pass

    return {
        "name": name,
        "price": price,
        "change": change,
        "change_pct": change_pct,
    }
