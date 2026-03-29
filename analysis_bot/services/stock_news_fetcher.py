"""
個股相關新聞抓取。

來源：Google News RSS（搜尋股票名稱+代碼）。
台股：{name} {ticker} 股票
美股：{name} {ticker} stock
"""
import asyncio
import logging
from datetime import datetime
from urllib.parse import quote

import feedparser

logger = logging.getLogger(__name__)


def _parse_date(entry) -> str:
    """從 feedparser entry 取得 MM/DD 格式日期。"""
    parsed = entry.get("published_parsed")
    if parsed and len(parsed) >= 2:
        return f"{parsed[1]:02d}/{parsed[2]:02d}"
    published = entry.get("published")
    if published:
        try:
            dt = datetime.strptime(published[:17], "%a, %d %b %Y")
            return f"{dt.month:02d}/{dt.day:02d}"
        except ValueError:
            pass
    return ""


async def fetch_stock_news(
    ticker: str,
    name: str,
    limit: int = 5,
    is_tw: bool = True,
) -> list[dict]:
    """
    抓取與該股票相關的新聞標題與連結。

    Args:
        ticker: 股票代碼
        name: 股票名稱（用於搜尋）
        limit: 最多幾筆
        is_tw: 是否為台股（影響搜尋關鍵字）

    Returns:
        [{"title": str, "url": str, "date": str}, ...]
    """
    keyword = f"{name} {ticker} 股票" if is_tw else f"{name} {ticker} stock"
    query = quote(keyword)
    url = (
        f"https://news.google.com/rss/search"
        f"?q={query}+when:30d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )

    try:
        feed = await asyncio.to_thread(feedparser.parse, url)
    except Exception as e:
        logger.debug("Google News RSS %s: %s", ticker, e)
        return []

    result = []
    for entry in feed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if title and link:
            date_str = _parse_date(entry)
            result.append({"title": title, "url": link, "date": date_str})
    return result
