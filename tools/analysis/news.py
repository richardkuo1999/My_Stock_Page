"""analysis.news — 新聞聚合 / 個股過濾（import raw/news_sources）。

組合層：把 raw/news_sources 的全部來源池做「快取 / 個股關鍵字過濾 / 去重 / 排序」。
個股過濾會 call lookup_stock_name 補公司中文名當關鍵字（台股標題用名不用代號）。

CLI（Agent 直接跑）:
  python tools/analysis/news.py [SYMBOL] [--limit N] [--all]
  python tools/analysis/news.py --fulltext <URL>   # 轉呼 raw 全文抓取

回傳: {"articles":[{title,source,date,url,summary}]}。
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx

# 直接跑時補 repo 根到 sys.path，以便 import tools.raw / tools.lookup_stock_name。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools.raw import news_sources as _raw
from tools.raw.news_sources import (
    DEFAULT_TIMEOUT,
    USER_AGENT,
    _deduplicate,
    _fetch_all_sources,
    _fetch_cnyes,
    _sort_by_date,
    fetch_fulltext,
)

logger = logging.getLogger(__name__)

NEWS_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "news_cache.json"
CACHE_TTL_SECONDS = 600  # 10 minutes

async def latest(force_refresh: bool = False) -> dict:
    """Fetch the latest news from all 15 sources, with a short-lived disk cache.

    Within CACHE_TTL_SECONDS, repeated calls return the cached result instead of
    re-hitting every source. Pass force_refresh=True to bypass the cache.

    Returns:
        dict with "articles" key containing list of article dicts.
    """
    if not force_refresh:
        cached = _read_news_cache()
        if cached is not None:
            logger.info("news: serving %d articles from cache", len(cached))
            return {"articles": cached}

    result = await _fetch_all_sources()
    _write_news_cache(result["articles"])
    return result



def _read_news_cache() -> list[dict] | None:
    """Return cached articles if the cache exists and is fresh, else None."""
    try:
        if not NEWS_CACHE_FILE.exists():
            return None
        data = json.loads(NEWS_CACHE_FILE.read_text(encoding="utf-8"))
        fetched_at = data.get("fetched_at", 0)
        if time.time() - fetched_at > CACHE_TTL_SECONDS:
            return None  # stale
        articles = data.get("articles")
        return articles if isinstance(articles, list) else None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read news cache: %s", e)
        return None


def _write_news_cache(articles: list[dict]) -> None:
    """Persist articles with a fetch timestamp."""
    try:
        NEWS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        NEWS_CACHE_FILE.write_text(
            json.dumps({"fetched_at": time.time(), "articles": articles}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Failed to write news cache: %s", e)



async def fetch(symbol: str | None = None, limit: int = 10) -> dict:
    """Fetch news, optionally filtered by a stock keyword.

    Args:
        symbol: A stock code (e.g. '2330') or company name (e.g. '台積電'). If a
            code is found in the local name cache, the company name is added as
            an extra search keyword (Taiwanese headlines use the name, not the
            code). Resolving an *unknown* code is the Agent's job — it calls
            tools/lookup_stock_name.py, which writes the answer back to the
            cache. This tool itself never calls the AI. If None, returns the
            latest news from all sources.
        limit: Maximum number of articles to return.

    Returns:
        dict with "articles" key containing list of article dicts.
    """
    if symbol is None:
        result = await latest()
        result["articles"] = result["articles"][:limit]
        return result

    # `symbol` is a stock code (e.g. 2330) or company name. Build search keywords:
    # the raw symbol plus, if the code is already in the local name cache, the
    # company name. The tool NEVER calls the AI itself — resolving an unknown
    # code → name is the Agent's job (it reads/writes the cache via the
    # lookup_stock_name.py tool). This keeps the pipeline:
    #   chat_bot → AI → tool → AI → tool   (AI orchestrates; tools stay pure)
    keywords = [symbol]
    name = _cached_stock_name(symbol)
    if name and name != symbol:
        keywords.append(name)

    # 1) "Database": the latest news already fetched from all 15 sources.
    # 2) Supplement with CNYES keyword search (low precision, but occasional
    #    exclusives). Merge, then filter locally by keyword relevance.
    latest_result = await latest()
    pool = list(latest_result.get("articles", []))

    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True
        ) as client:
            pool.extend(await _fetch_cnyes(client, symbol=symbol, limit=limit))
    except Exception as e:
        logger.warning("CNYES supplement search failed for %s: %s", symbol, e)

    pool = _deduplicate(pool)
    matched = _filter_by_keywords(pool, keywords)
    matched = _sort_by_date(matched)
    return {"articles": matched[:limit]}


def _filter_by_keywords(articles: list[dict], keywords: list[str]) -> list[dict]:
    """Keep only articles whose title or summary contains any keyword."""
    if not keywords:
        return articles
    lowered = [k.lower() for k in keywords if k]
    result = []
    for a in articles:
        haystack = f"{a.get('title', '')} {a.get('summary', '')}".lower()
        if any(k in haystack for k in lowered):
            result.append(a)
    return result


def _cached_stock_name(symbol: str) -> str | None:
    """Return the company name for a stock code from the local cache, or None.

    Pure data lookup — no AI. Delegates to the shared lookup_stock_name tool so
    both tools share one JSON file + seed. Resolving an *unknown* code is the
    Agent's job (it calls tools/lookup_stock_name.py --set to write it back).
    """
    if not symbol.isdigit():
        return None
    return _lookup_get_name(symbol)


def _lookup_get_name(symbol: str) -> str | None:
    """Import-tolerant accessor to the shared name cache."""
    try:
        from tools.lookup_stock_name import get_name
    except ImportError:  # pragma: no cover - when run as a script from tools/
        try:
            from lookup_stock_name import get_name
        except ImportError:
            return None
    return get_name(symbol)



# --- CLI ---
if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--fulltext" and len(args) > 1:
        result = asyncio.run(fetch_fulltext(args[1]))
    else:
        symbol = None
        limit = 10
        for i, a in enumerate(args):
            if a == "--limit" and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    pass
            elif not a.startswith("--"):
                symbol = a
        result = asyncio.run(fetch(symbol, limit))
    print(json.dumps(result, ensure_ascii=False))
