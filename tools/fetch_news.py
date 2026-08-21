"""fetch_news — 取得指定股票的最新新聞
用法: python tools/fetch_news.py [SYMBOL] [--limit N] [--all]
回傳: JSON {"articles": [{title, source, date, url, summary}]}
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

import feedparser
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0
DEFAULT_LIMIT = 10
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) StockBot/1.0"

# --- Source Definitions ---

SOURCES = [
    {"name": "CNYES", "type": "json", "url": "https://news.cnyes.com/api/v3/news/category/headline?limit=10"},
    {"name": "MoneyDJ", "type": "rss", "url": "https://www.moneydj.com/funddj/xml/newsfeed/newsfeed.aspx"},
    {"name": "Yahoo股市", "type": "rss", "url": "https://tw.stock.yahoo.com/rss"},
    {"name": "UDN財經", "type": "rss", "url": "https://udn.com/rssfeed/news/6/7241/0?ch=news"},
    {"name": "UAnalyze", "type": "json", "url": "https://data.uanalyze.twobitto.com/api/report-summaries"},
    {"name": "Fugle", "type": "json", "url": "https://www.fugle.tw/api/v1/posts?limit=10"},
    {"name": "Vocus", "type": "vocus", "url": "https://vocus.cc"},
    {"name": "MacroMicro", "type": "rss", "url": "https://morss.it/https://www.macromicro.me/blog/rss"},
    {"name": "FinGuider", "type": "json", "url": "https://api.finguider.com/api/v1/reports?limit=10"},
    {"name": "Fintastic", "type": "rss", "url": "https://morss.it/https://www.fintastic.com.tw/blog/rss"},
    {"name": "Forecastock", "type": "rss", "url": "https://morss.it/https://www.forecastock.com/blog.xml"},
    {"name": "NewsDigestAI", "type": "rss", "url": "https://www.newsdigestai.com/feed"},
    {"name": "SinoTrade", "type": "json", "url": "https://richclub.sinotrade.com.tw/api/post/list?limit=10"},
    {"name": "Pocket學堂", "type": "json", "url": "https://www.pocket.tw/api/articles?limit=10"},
    {"name": "Buffett+Marks", "type": "static", "url": ""},
]

# Vocus authors to track
VOCUS_AUTHORS = ["@ieobserve", "@miula", "65ab564cfd897800018a88cc"]

# Static resources (Buffett Letters + Howard Marks Memos)
STATIC_ARTICLES = [
    {
        "title": "Berkshire Hathaway Annual Letters",
        "source": "Buffett+Marks",
        "date": "",
        "url": "https://www.berkshirehathaway.com/letters/letters.html",
        "summary": "Warren Buffett's annual shareholder letters",
    },
    {
        "title": "Howard Marks Memos",
        "source": "Buffett+Marks",
        "date": "",
        "url": "https://www.oaktreecapital.com/insights/memo-archive",
        "summary": "Howard Marks investment memos archive",
    },
]


def _make_article(title: str, source: str, date: str, url: str, summary: str = "") -> dict:
    """Build a standardized article dict."""
    return {
        "title": title.strip() if title else "",
        "source": source,
        "date": date,
        "url": url.strip() if url else "",
        "summary": summary.strip() if summary else "",
    }


def _parse_date(date_str: str | None) -> str:
    """Try to parse a date string into ISO format. Return empty string on failure."""
    if not date_str:
        return ""
    try:
        # feedparser's time struct
        if hasattr(date_str, "tm_year"):
            dt = datetime(*date_str[:6])
            return dt.isoformat()
        return date_str
    except Exception:
        return date_str if isinstance(date_str, str) else ""


def _parse_rss_date(entry: dict) -> str:
    """Extract date from RSS entry, trying multiple fields."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                dt = datetime(*parsed[:6])
                return dt.isoformat()
            except Exception:
                pass
    for field in ("published", "updated"):
        val = entry.get(field)
        if val:
            return val
    return ""


# --- Fetch Coroutines ---


async def _fetch_rss(source: dict, client: httpx.AsyncClient) -> list[dict]:
    """Generic RSS feed parser. Fetches and parses RSS/Atom feeds."""
    url = source["url"]
    name = source["name"]
    try:
        r = await client.get(url)
        if r.status_code != 200:
            logger.warning("RSS %s returned status %d", name, r.status_code)
            return []
        feed = feedparser.parse(r.text)
        articles = []
        for entry in feed.entries[:DEFAULT_LIMIT]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            date = _parse_rss_date(entry)
            summary = entry.get("summary", "") or entry.get("description", "")
            articles.append(_make_article(title, name, date, link, summary))
        return articles
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", name, e)
        return []


async def _fetch_cnyes(client: httpx.AsyncClient, symbol: str | None = None, limit: int = 10) -> list[dict]:
    """Fetch from CNYES API. Optionally filter by stock symbol."""
    if symbol:
        url = f"https://news.cnyes.com/api/v3/news/category/headline?limit={limit}&keyword={symbol}"
    else:
        url = f"https://news.cnyes.com/api/v3/news/category/headline?limit={limit}"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            logger.warning("CNYES returned status %d", r.status_code)
            return []
        data = r.json()
        items = data.get("items", {}).get("data", [])
        if not items:
            # Try alternate response structure
            items = data.get("data", [])
        articles = []
        for item in items[:limit]:
            title = item.get("title", "")
            news_id = item.get("newsId", "")
            url_link = f"https://news.cnyes.com/news/id/{news_id}" if news_id else ""
            pub_at = item.get("publishAt", 0)
            date = ""
            if pub_at:
                try:
                    date = datetime.fromtimestamp(pub_at).isoformat()
                except (ValueError, OSError):
                    date = str(pub_at)
            summary = item.get("summary", "") or item.get("content", "")[:200]
            articles.append(_make_article(title, "CNYES", date, url_link, summary))
        return articles
    except Exception as e:
        logger.warning("CNYES fetch failed: %s", e)
        return []


async def _fetch_uanalyze(client: httpx.AsyncClient) -> list[dict]:
    """Fetch from UAnalyze API."""
    url = "https://data.uanalyze.twobitto.com/api/report-summaries"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            logger.warning("UAnalyze returned status %d", r.status_code)
            return []
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", [])
        articles = []
        for item in items[:DEFAULT_LIMIT]:
            title = item.get("title", "") or item.get("name", "")
            url_link = item.get("url", "") or item.get("link", "")
            date = item.get("date", "") or item.get("publishedAt", "")
            summary = item.get("summary", "") or item.get("description", "")
            articles.append(_make_article(title, "UAnalyze", date, url_link, summary))
        return articles
    except Exception as e:
        logger.warning("UAnalyze fetch failed: %s", e)
        return []


async def _fetch_fugle_posts(client: httpx.AsyncClient) -> list[dict]:
    """Fetch from Fugle posts API."""
    url = "https://www.fugle.tw/api/v1/posts?limit=10"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            logger.warning("Fugle posts returned status %d", r.status_code)
            return []
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", [])
        articles = []
        for item in items[:DEFAULT_LIMIT]:
            title = item.get("title", "")
            url_link = item.get("url", "") or item.get("link", "")
            date = item.get("date", "") or item.get("publishedAt", "") or item.get("createdAt", "")
            summary = item.get("summary", "") or item.get("description", "")
            articles.append(_make_article(title, "Fugle", date, url_link, summary))
        return articles
    except Exception as e:
        logger.warning("Fugle posts fetch failed: %s", e)
        return []


async def _fetch_vocus(client: httpx.AsyncClient) -> list[dict]:
    """Fetch from Vocus for tracked authors."""
    articles = []
    for author in VOCUS_AUTHORS:
        author_id = author.lstrip("@")
        url = f"https://vocus.cc/api/users/{author_id}/articles"
        try:
            r = await client.get(url)
            if r.status_code != 200:
                # Try alternative URL pattern
                url_alt = f"https://vocus.cc/user/{author}"
                r = await client.get(url_alt)
                if r.status_code != 200:
                    continue
                # Can't parse HTML easily; skip this author
                continue
            data = r.json()
            items = data if isinstance(data, list) else data.get("articles", [])
            for item in items[:5]:
                title = item.get("title", "")
                slug = item.get("slug", "") or item.get("_id", "")
                url_link = f"https://vocus.cc/{author_id}/{slug}" if slug else ""
                date = item.get("publishedAt", "") or item.get("createdAt", "")
                summary = item.get("summary", "") or item.get("description", "")
                articles.append(_make_article(title, "Vocus", date, url_link, summary))
        except Exception as e:
            logger.warning("Vocus fetch failed for %s: %s", author, e)
    return articles


async def _fetch_finguider(client: httpx.AsyncClient) -> list[dict]:
    """Fetch from FinGuider API."""
    url = "https://api.finguider.com/api/v1/reports?limit=10"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            logger.warning("FinGuider returned status %d", r.status_code)
            return []
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", [])
        articles = []
        for item in items[:DEFAULT_LIMIT]:
            title = item.get("title", "")
            url_link = item.get("url", "") or item.get("link", "")
            date = item.get("date", "") or item.get("publishedAt", "")
            summary = item.get("summary", "") or item.get("description", "")
            articles.append(_make_article(title, "FinGuider", date, url_link, summary))
        return articles
    except Exception as e:
        logger.warning("FinGuider fetch failed: %s", e)
        return []


async def _fetch_sinotrade(client: httpx.AsyncClient) -> list[dict]:
    """Fetch from SinoTrade Rich Club API."""
    url = "https://richclub.sinotrade.com.tw/api/post/list?limit=10"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            logger.warning("SinoTrade returned status %d", r.status_code)
            return []
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", data.get("posts", []))
        articles = []
        for item in items[:DEFAULT_LIMIT]:
            title = item.get("title", "")
            url_link = item.get("url", "") or item.get("link", "")
            date = item.get("date", "") or item.get("publishedAt", "") or item.get("createdAt", "")
            summary = item.get("summary", "") or item.get("description", "")
            articles.append(_make_article(title, "SinoTrade", date, url_link, summary))
        return articles
    except Exception as e:
        logger.warning("SinoTrade fetch failed: %s", e)
        return []


async def _fetch_pocket(client: httpx.AsyncClient) -> list[dict]:
    """Fetch from Pocket學堂 API."""
    url = "https://www.pocket.tw/api/articles?limit=10"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            logger.warning("Pocket學堂 returned status %d", r.status_code)
            return []
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", data.get("articles", []))
        articles = []
        for item in items[:DEFAULT_LIMIT]:
            title = item.get("title", "")
            url_link = item.get("url", "") or item.get("link", "")
            date = item.get("date", "") or item.get("publishedAt", "")
            summary = item.get("summary", "") or item.get("description", "")
            articles.append(_make_article(title, "Pocket學堂", date, url_link, summary))
        return articles
    except Exception as e:
        logger.warning("Pocket學堂 fetch failed: %s", e)
        return []


async def _fetch_static() -> list[dict]:
    """Return static reference articles (Buffett + Marks)."""
    return STATIC_ARTICLES.copy()


# --- Dispatch ---


async def _dispatch_source(source: dict, client: httpx.AsyncClient) -> list[dict]:
    """Dispatch to the correct fetcher based on source type."""
    stype = source["type"]
    name = source["name"]

    if stype == "rss":
        return await _fetch_rss(source, client)
    elif stype == "json":
        if name == "CNYES":
            return await _fetch_cnyes(client)
        elif name == "UAnalyze":
            return await _fetch_uanalyze(client)
        elif name == "Fugle":
            return await _fetch_fugle_posts(client)
        elif name == "FinGuider":
            return await _fetch_finguider(client)
        elif name == "SinoTrade":
            return await _fetch_sinotrade(client)
        elif name == "Pocket學堂":
            return await _fetch_pocket(client)
        else:
            logger.warning("Unknown JSON source: %s", name)
            return []
    elif stype == "vocus":
        return await _fetch_vocus(client)
    elif stype == "static":
        return await _fetch_static()
    else:
        logger.warning("Unknown source type: %s for %s", stype, name)
        return []


# --- Deduplication and Sorting ---


def _deduplicate(articles: list[dict]) -> list[dict]:
    """Remove duplicate articles by URL."""
    seen_urls: set[str] = set()
    unique = []
    for article in articles:
        url = article.get("url", "")
        if not url or url not in seen_urls:
            if url:
                seen_urls.add(url)
            unique.append(article)
    return unique


def _sort_by_date(articles: list[dict]) -> list[dict]:
    """Sort articles by date descending. Articles without dates go to the end."""

    def sort_key(article: dict) -> str:
        date = article.get("date", "")
        return date if date else "0000-00-00"

    return sorted(articles, key=sort_key, reverse=True)


# --- Public API ---


async def latest() -> dict:
    """Fetch from all 15 sources in parallel.

    Returns:
        dict with "articles" key containing list of article dicts.
    """
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True) as client:
        tasks = [_dispatch_source(source, client) for source in SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles: list[dict] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Source %s failed: %s", SOURCES[i]["name"], result)
            continue
        if isinstance(result, list):
            all_articles.extend(result)

    all_articles = _deduplicate(all_articles)
    all_articles = _sort_by_date(all_articles)
    return {"articles": all_articles}


async def fetch(symbol: str | None = None, limit: int = 10) -> dict:
    """Fetch news, optionally filtered by stock symbol.

    Args:
        symbol: Stock symbol to search for (e.g. '2330'). If None, returns latest from all sources.
        limit: Maximum number of articles to return.

    Returns:
        dict with "articles" key containing list of article dicts.
    """
    if symbol is None:
        result = await latest()
        result["articles"] = result["articles"][:limit]
        return result

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True) as client:
        articles = await _fetch_cnyes(client, symbol=symbol, limit=limit)

    articles = _deduplicate(articles)
    articles = _sort_by_date(articles)
    return {"articles": articles[:limit]}


# --- CLI Entry Point ---


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--all" in args:
        result = asyncio.run(latest())
    elif args and not args[0].startswith("--"):
        symbol = args[0]
        limit = DEFAULT_LIMIT
        if "--limit" in args:
            try:
                limit = int(args[args.index("--limit") + 1])
            except (IndexError, ValueError):
                pass
        result = asyncio.run(fetch(symbol, limit))
    else:
        # No symbol, no --all → latest with default limit
        limit = DEFAULT_LIMIT
        if "--limit" in args:
            try:
                limit = int(args[args.index("--limit") + 1])
            except (IndexError, ValueError):
                pass
        result = asyncio.run(fetch(None, limit))

    print(json.dumps(result, ensure_ascii=False))
