"""fetch_news — 取得指定股票的最新新聞
用法: python tools/fetch_news.py [SYMBOL] [--limit N] [--all]
回傳: JSON {"articles": [{title, source, date, url, summary}]}
"""

import asyncio
import html
import json
import logging
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import feedparser
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

try:
    from curl_cffi import requests as cffi_requests
except ImportError:  # pragma: no cover - optional dependency
    cffi_requests = None

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0
DEFAULT_LIMIT = 10
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) StockBot/1.0"
# TLS-fingerprint impersonation profile for curl_cffi (bypasses Cloudflare)
CFFI_IMPERSONATE = "chrome120"

# News content cache: latest() writes here and reuses it within CACHE_TTL to
# avoid re-hitting 16 sources on every /news, @mention, or scheduled run.
NEWS_CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "news_cache.json"
CACHE_TTL_SECONDS = 600  # 10 minutes


# --- Source Definitions ---
# Each source has a `name` and a `type` used for dispatch. Verified URLs live
# inside the individual fetchers (from the old working news_parser.py).

SOURCES = [
    {"name": "CNYES", "type": "json", "url": "https://news.cnyes.com/api/v3/news/category/headline?limit=10"},
    {"name": "MoneyDJ", "type": "rss", "url": "https://www.moneydj.com/KMDJ/RssCenter.aspx?svc=NR&fno=1&arg=MB010000"},
    {"name": "Yahoo股市", "type": "rss", "url": "https://tw.stock.yahoo.com/rss?category=news"},
    {"name": "UDN財經", "type": "udn", "url": "https://money.udn.com/rssfeed/news/1001/5591"},
    {"name": "UAnalyze", "type": "uanalyze", "url": "https://uanalyze.com.tw/articles"},
    {"name": "Fugle", "type": "fugle", "url": "https://blog.fugle.tw/topic/industry-analysis"},
    {"name": "Vocus", "type": "vocus", "url": "https://vocus.cc"},
    {"name": "MacroMicro", "type": "macromicro", "url": "https://www.macromicro.me/rss"},
    {"name": "FinGuider", "type": "finguider", "url": "https://finguider.cc/Api/article/"},
    {"name": "Fintastic", "type": "fintastic", "url": "https://fintastic.trading/wp-json/wp/v2/posts"},
    {
        "name": "Forecastock",
        "type": "forecastock",
        "url": "https://www.forecastock.tw/category/%E5%80%8B%E8%82%A1%E5%A0%B1%E5%91%8A",
    },
    {"name": "NewsDigestAI", "type": "rss", "url": "https://feed.cqd.tw/ndai"},
    {"name": "SinoTrade", "type": "sinotrade", "url": "https://www.sinotrade.com.tw/richclub/api/graphql"},
    {"name": "Pocket學堂", "type": "pocket", "url": "https://www.pocket.tw/invest_news/api/invest_news/"},
    {
        "name": "UAnalyze專欄",
        "type": "ua_column",
        "url": "https://api.uanalyze.com.tw/data/fetch/column/search",
    },
    {"name": "Buffett+Marks", "type": "static", "url": ""},
]

# Vocus authors to track
VOCUS_AUTHORS = ["@ieobserve", "@miula", "65ab564cfd897800018a88cc"]

# UDN money feeds (Industry / Stock / International / Cross-Strait)
UDN_FEEDS = [
    "https://money.udn.com/rssfeed/news/1001/5591",
    "https://money.udn.com/rssfeed/news/1001/5590",
    "https://money.udn.com/rssfeed/news/1001/5588",
    "https://money.udn.com/rssfeed/news/1001/5589",
]

# Fugle blog category pages
FUGLE_CATEGORIES = [
    "https://blog.fugle.tw/topic/industry-analysis",
    "https://blog.fugle.tw/topic/stock-analysis",
    "https://blog.fugle.tw/topic/us-stock-summary",
    "https://blog.fugle.tw/topic/earnings-call-memo",
    "https://blog.fugle.tw/topic/current-events-commentary",
]

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
        "url": "https://www.oaktreecapital.com/insights/memos",
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


def _parse_feed_text(text: str, name: str) -> list[dict]:
    """Parse RSS/Atom feed text into article dicts."""
    feed = feedparser.parse(text)
    articles = []
    for entry in feed.entries[:DEFAULT_LIMIT]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        date = _parse_rss_date(entry)
        summary = entry.get("summary", "") or entry.get("description", "")
        articles.append(_make_article(title, name, date, link, summary))
    return articles


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
        return _parse_feed_text(r.text, name)
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", name, e or type(e).__name__)
        return []


async def _fetch_moneydj(client: httpx.AsyncClient) -> list[dict]:
    """MoneyDJ RSS. Has SSL cert issues → use a short-lived verify=False client."""
    url = "https://www.moneydj.com/KMDJ/RssCenter.aspx?svc=NR&fno=1&arg=MB010000"
    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True, verify=False
        ) as insecure:
            r = await insecure.get(url)
            if r.status_code != 200:
                logger.warning("MoneyDJ returned status %d", r.status_code)
                return []
            return _parse_feed_text(r.text, "MoneyDJ")
    except Exception as e:
        logger.warning("MoneyDJ fetch failed: %s", e)
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
            summary = item.get("summary", "") or (item.get("content", "") or "")[:200]
            articles.append(_make_article(title, "CNYES", date, url_link, summary))
        return articles
    except Exception as e:
        logger.warning("CNYES fetch failed: %s", e)
        return []


async def _fetch_udn(client: httpx.AsyncClient) -> list[dict]:
    """UDN財經: fetch 4 RSS feeds in parallel and merge."""

    async def fetch_one(url: str) -> list[dict]:
        try:
            r = await client.get(url)
            if r.status_code != 200:
                return []
            return _parse_feed_text(r.text, "UDN財經")
        except Exception as e:
            logger.warning("UDN feed failed %s: %s", url, e)
            return []

    results = await asyncio.gather(*[fetch_one(u) for u in UDN_FEEDS], return_exceptions=True)
    merged: list[dict] = []
    for res in results:
        if isinstance(res, list):
            merged.extend(res)
    return merged


async def _fetch_uanalyze(client: httpx.AsyncClient) -> list[dict]:
    """UAnalyze: HTML page parsed with BeautifulSoup."""
    url = "https://uanalyze.com.tw/articles"
    try:
        r = await client.get(url)
        if r.status_code != 200:
            logger.warning("UAnalyze returned status %d", r.status_code)
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        block = soup.select(".article-list")
        items = block[0].select(".article-content") if block else []
        articles = []
        for item in items[:DEFAULT_LIMIT]:
            title_elem = item.select_one(".article-content__title")
            link_elem = item.select_one("a")
            if title_elem and link_elem and link_elem.get("href"):
                title = title_elem.get_text(strip=True)
                link = link_elem["href"]
                articles.append(_make_article(title, "UAnalyze", "", link, ""))
        return articles
    except Exception as e:
        logger.warning("UAnalyze fetch failed: %s", e)
        return []


async def _fetch_fugle(client: httpx.AsyncClient) -> list[dict]:
    """Fugle blog: fetch category pages in parallel, extract /post/ links."""

    async def fetch_cat(cat_url: str) -> list[dict]:
        try:
            r = await client.get(cat_url)
            if r.status_code != 200:
                return []
            soup = BeautifulSoup(r.text, "html.parser")
            found = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                title = a.get_text(strip=True)
                if not title:
                    continue
                if "/post/" in href:
                    full = f"https://blog.fugle.tw{href}" if href.startswith("/") else href
                    found.append(_make_article(title, "Fugle", "", full, ""))
            return found
        except Exception as e:
            logger.warning("Fugle category failed %s: %s", cat_url, e)
            return []

    results = await asyncio.gather(*[fetch_cat(u) for u in FUGLE_CATEGORIES], return_exceptions=True)
    articles: list[dict] = []
    seen: set[str] = set()
    for res in results:
        if isinstance(res, list):
            for art in res:
                if art["url"] not in seen:
                    seen.add(art["url"])
                    articles.append(art)
    return articles[:DEFAULT_LIMIT]


async def _fetch_vocus(client: httpx.AsyncClient) -> list[dict]:
    """Vocus: Next.js SSR page. Parse __NEXT_DATA__ JSON, fallback to /article/ links."""
    link_prefix = "https://vocus.cc"
    articles: list[dict] = []
    for user_id in VOCUS_AUTHORS:
        url = f"https://vocus.cc/user/{user_id}"
        try:
            r = await client.get(url)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            found: list[dict] = []

            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                try:
                    data = json.loads(nd.string)
                    props = data.get("props", {}).get("pageProps", {})
                    items = props.get("articles") or props.get("articleList") or []
                    if isinstance(items, dict):
                        items = items.get("items") or items.get("data") or []
                    for art in items:
                        if not isinstance(art, dict):
                            continue
                        title = art.get("title", "")
                        slug = art.get("slug") or art.get("_id") or art.get("id", "")
                        if title and slug:
                            url_path = f"/article/{slug}" if "/" not in str(slug) else str(slug)
                            found.append(_make_article(title, "Vocus", "", link_prefix + url_path, ""))
                except (ValueError, KeyError):
                    pass

            # Fallback: scan a[href*='/article/']
            if not found:
                seen = set()
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "/article/" not in href:
                        continue
                    title = a.get_text(strip=True)
                    if not title or len(title) < 4:
                        continue
                    full_url = href if href.startswith("http") else link_prefix + href
                    if full_url not in seen:
                        seen.add(full_url)
                        found.append(_make_article(title, "Vocus", "", full_url, ""))

            articles.extend(found[:5])
        except Exception as e:
            logger.warning("Vocus fetch failed for %s: %s", user_id, e)
    return articles


async def _fetch_finguider(client: httpx.AsyncClient) -> list[dict]:
    """FinGuider: public JSON API. May have SSL issue → fallback to verify=False."""
    url = "https://finguider.cc/Api/article/"
    params = {"hot_new": "new", "page": 1}

    async def do_fetch(cli: httpx.AsyncClient) -> httpx.Response:
        return await cli.get(url, params=params)

    try:
        try:
            r = await do_fetch(client)
        except (httpx.ConnectError, httpx.TransportError) as ssl_err:
            logger.warning("FinGuider retrying with verify=False: %s", ssl_err)
            headers = {"User-Agent": USER_AGENT}
            async with httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True, verify=False
            ) as insecure:
                r = await do_fetch(insecure)
        if r.status_code != 200:
            logger.warning("FinGuider returned status %d", r.status_code)
            return []
        data = r.json()
        items = data.get("results", [])
        articles = []
        for item in items[:DEFAULT_LIMIT]:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "")
            art_id = item.get("id")
            if not title:
                continue
            link = (
                f"https://finguider.cc/Article/ArticleIndex/{art_id}"
                if art_id
                else "https://finguider.cc/Article"
            )
            summary = item.get("content", "") or item.get("describe", "")
            articles.append(_make_article(str(title), "FinGuider", "", link, str(summary)))
        return articles
    except Exception as e:
        logger.warning("FinGuider fetch failed: %s", e)
        return []


async def _fetch_sinotrade(client: httpx.AsyncClient) -> list[dict]:
    """SinoTrade Rich Club: GraphQL POST with verify=False."""
    endpoint = "https://www.sinotrade.com.tw/richclub/api/graphql"
    limit = 20
    query = (
        "query {"
        f' clientGetArticleList(input:{{channel:"industry",limit:{limit},page:0}}) {{'
        "   filtered { _id title pubDate image }"
        " }"
        "}"
    )
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.sinotrade.com.tw",
        "Referer": "https://www.sinotrade.com.tw/richclub/industry",
        "User-Agent": USER_AGENT,
    }
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, follow_redirects=True, verify=False
        ) as insecure:
            r = await insecure.post(endpoint, json={"query": query}, headers=headers)
            if r.status_code != 200:
                logger.warning("SinoTrade returned status %d", r.status_code)
                return []
            data = r.json()
        items = (data or {}).get("data", {}).get("clientGetArticleList", {}).get("filtered", [])
        articles = []
        for item in items[:DEFAULT_LIMIT]:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            cid = item.get("_id")
            if not title:
                continue
            url = "https://www.sinotrade.com.tw/richclub/industry"
            if cid:
                article_key = urllib.parse.quote(f"x-{cid}")
                url = (
                    f"https://www.sinotrade.com.tw/richclub/content?article={article_key}"
                    "&channel=industry&type=article"
                )
            articles.append(_make_article(str(title), "SinoTrade", "", url, ""))
        return articles
    except Exception as e:
        logger.warning("SinoTrade fetch failed: %s", e)
        return []


async def _fetch_pocket(client: httpx.AsyncClient) -> list[dict]:
    """Pocket學堂: JSON API with verify=False (SSL cert issue)."""
    url = "https://www.pocket.tw/invest_news/api/invest_news/"
    params = {"page": 1, "category": "", "keyword": ""}
    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True, verify=False
        ) as insecure:
            r = await insecure.get(url, params=params)
            if r.status_code != 200:
                logger.warning("Pocket學堂 returned status %d", r.status_code)
                return []
            payload = r.json()
        if not isinstance(payload, dict) or str(payload.get("code")) != "0":
            logger.warning("Pocket學堂 unexpected payload code")
            return []
        items = payload.get("data") or []
        articles = []
        for item in items[:DEFAULT_LIMIT]:
            if not isinstance(item, dict):
                continue
            title = item.get("Title") or item.get("title")
            slug = item.get("slug")
            if not title or not slug:
                continue
            link = str(slug)
            if link.startswith("/"):
                link = f"https://www.pocket.tw{link}"
            summary = item.get("description") or item.get("meta_description") or ""
            articles.append(_make_article(str(title), "Pocket學堂", "", link, str(summary)))
        return articles
    except Exception as e:
        logger.warning("Pocket學堂 fetch failed: %s", e)
        return []


async def _fetch_static() -> list[dict]:
    """Return static reference articles (Buffett + Marks)."""
    return [dict(a) for a in STATIC_ARTICLES]


async def _fetch_forecastock(client: httpx.AsyncClient) -> list[dict]:
    """Forecastock: direct HTML scrape (morss proxy is unreliable).

    Extracts article links via the `a.articleListItem__link` selector,
    same target the old morss proxy config used.
    """
    url = "https://www.forecastock.tw/category/%E5%80%8B%E8%82%A1%E5%A0%B1%E5%91%8A"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True, verify=False
        ) as cli:
            r = await cli.get(url)
            if r.status_code != 200:
                logger.warning("Forecastock returned status %d", r.status_code)
                return []
        soup = BeautifulSoup(r.text, "html.parser")
        articles = []
        for a in soup.select("a.articleListItem__link")[:DEFAULT_LIMIT]:
            href = a.get("href", "")
            title = a.get_text(strip=True)
            # Titles are prefixed with 前往 on this site; strip it.
            if title.startswith("前往"):
                title = title[2:]
            if not href or not title:
                continue
            full = href if href.startswith("http") else f"https://www.forecastock.tw{href}"
            articles.append(_make_article(title, "Forecastock", "", full, ""))
        return articles
    except Exception as e:
        logger.warning("Forecastock fetch failed: %s", e)
        return []


def _cffi_get(url: str, params: dict | None = None):
    """Blocking curl_cffi GET with Chrome TLS fingerprint. Returns response or None."""
    if cffi_requests is None:
        logger.warning("curl_cffi not installed; cannot bypass Cloudflare for %s", url)
        return None
    return cffi_requests.get(
        url, params=params, impersonate=CFFI_IMPERSONATE, timeout=DEFAULT_TIMEOUT
    )


async def _fetch_macromicro(client: httpx.AsyncClient) -> list[dict]:
    """MacroMicro RSS behind Cloudflare — fetch via curl_cffi TLS impersonation."""
    url = "https://www.macromicro.me/rss"
    try:
        r = await asyncio.to_thread(_cffi_get, url)
        if r is None or r.status_code != 200:
            logger.warning("MacroMicro returned status %s", getattr(r, "status_code", "N/A"))
            return []
        return _parse_feed_text(r.text, "MacroMicro")
    except Exception as e:
        logger.warning("MacroMicro fetch failed: %s", e)
        return []


async def _fetch_fintastic(client: httpx.AsyncClient) -> list[dict]:
    """Fintastic WordPress JSON API. A full browser UA is enough to pass its
    Cloudflare rule (curl_cffi's TLS fingerprint is actually blocked here)."""
    url = "https://fintastic.trading/wp-json/wp/v2/posts"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True, verify=False
        ) as cli:
            r = await cli.get(url, params={"per_page": DEFAULT_LIMIT})
            if r.status_code != 200:
                logger.warning("Fintastic returned status %d", r.status_code)
                return []
            posts = r.json()
        articles = []
        for post in posts[:DEFAULT_LIMIT]:
            if not isinstance(post, dict):
                continue
            title = (post.get("title") or {}).get("rendered", "")
            link = post.get("link", "")
            date = post.get("date", "")
            excerpt = (post.get("excerpt") or {}).get("rendered", "")
            # Strip HTML tags from WordPress excerpt
            if excerpt:
                excerpt = BeautifulSoup(excerpt, "html.parser").get_text(strip=True)
            if title and link:
                articles.append(_make_article(title, "Fintastic", date, link, excerpt))
        return articles
    except Exception as e:
        logger.warning("Fintastic fetch failed: %s", e)
        return []


def _strip_html(raw: str, limit: int = 150) -> str:
    """Collapse HTML into plain text and truncate. No new heavy deps."""
    if not raw:
        return ""
    # Drop tags, unescape entities, collapse whitespace.
    # Unescape entities first (so &lt;x&gt; becomes literal <x>), then drop all
    # tags, then collapse whitespace. This ordering stops entity-encoded angle
    # brackets from re-introducing "<" after tag removal.
    text = html.unescape(raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


async def _fetch_ua_column(client: httpx.AsyncClient) -> list[dict]:
    """UAnalyze 專欄: JWT-authed JSON API (api.uanalyze.com.tw/data/fetch/column/search).

    Returns the latest 15 columns. Paid content with no public permalink, so
    `url` points at the pro homepage. Pure data — no AI. Returns [] on any
    failure so it never breaks the other sources.
    """
    # Local import with tools.* / bare fallback (works as module or script).
    try:
        from tools.uanalyze import _auth
    except ImportError:  # pragma: no cover - when run as a script from tools/
        try:
            from uanalyze import _auth
        except ImportError:
            logger.warning("UAnalyze專欄: cannot import _auth")
            return []

    token = await _auth.ensure_token()
    if not token:
        logger.warning("UAnalyze專欄: no token, skipping")
        return []

    url = "https://api.uanalyze.com.tw/data/fetch/column/search"
    headers = _auth.jwt_headers()
    headers["Origin"] = "https://pro.uanalyze.com.tw"
    params = {"Keywords": "", "page": 1, "per_page": 15}
    try:
        r = await client.get(url, params=params, headers=headers)
        if r.status_code != 200:
            logger.warning("UAnalyze專欄 returned status %d", r.status_code)
            return []
        data = r.json()
        columns = (data or {}).get("data", {}).get("columns", [])
        articles = []
        for item in columns[:15]:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "")
            if not title:
                continue
            date = (item.get("created_at") or "")[:10]
            summary = _strip_html(item.get("content") or "", 150)
            articles.append(
                _make_article(title, "UAnalyze專欄", date, "", summary)
            )
        return articles
    except Exception as e:
        logger.warning("UAnalyze專欄 fetch failed: %s", e)
        return []


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
        logger.warning("Unknown JSON source: %s", name)
        return []
    elif stype == "udn":
        return await _fetch_udn(client)
    elif stype == "uanalyze":
        return await _fetch_uanalyze(client)
    elif stype == "fugle":
        return await _fetch_fugle(client)
    elif stype == "vocus":
        return await _fetch_vocus(client)
    elif stype == "finguider":
        return await _fetch_finguider(client)
    elif stype == "sinotrade":
        return await _fetch_sinotrade(client)
    elif stype == "pocket":
        return await _fetch_pocket(client)
    elif stype == "forecastock":
        return await _fetch_forecastock(client)
    elif stype == "macromicro":
        return await _fetch_macromicro(client)
    elif stype == "fintastic":
        return await _fetch_fintastic(client)
    elif stype == "ua_column":
        return await _fetch_ua_column(client)
    elif stype == "static":
        return await _fetch_static()

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


def _diversify_by_source(articles: list[dict], limit: int) -> list[dict]:
    """Pick up to `limit` articles spread across sources (round-robin).

    Articles are assumed pre-sorted (e.g. by date desc). Group by source keeping
    that order, then take one per source in rotation so a single prolific source
    (e.g. CNYES) can't dominate the head of the list.
    """
    from collections import OrderedDict

    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for a in articles:
        groups.setdefault(a.get("source", "?"), []).append(a)

    picked: list[dict] = []
    while len(picked) < limit and any(groups.values()):
        for src in list(groups.keys()):
            if groups[src]:
                picked.append(groups[src].pop(0))
                if len(picked) >= limit:
                    break
    return picked


def _sort_by_date(articles: list[dict]) -> list[dict]:
    """Sort articles by date descending. Articles without dates go to the end."""

    def sort_key(article: dict) -> str:
        date = article.get("date", "")
        return date if date else "0000-00-00"

    return sorted(articles, key=sort_key, reverse=True)


# --- Public API ---


async def latest(force_refresh: bool = False) -> dict:
    """Fetch the latest news from all 16 sources, with a short-lived disk cache.

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


async def _fetch_all_sources() -> dict:
    """Fetch from all 16 sources in parallel (no cache)."""
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True) as client:
        # MoneyDJ needs verify=False, dispatched via type "rss" name "MoneyDJ" →
        # route it to its dedicated fetcher instead.
        tasks = []
        for source in SOURCES:
            if source["name"] == "MoneyDJ":
                tasks.append(_fetch_moneydj(client))
            else:
                tasks.append(_dispatch_source(source, client))
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

    # 1) "Database": the latest news already fetched from all 16 sources.
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



# --- CLI Entry Point ---


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--all" in args:
        # CLI --all always hits live sources (bypasses cache) for debugging.
        result = asyncio.run(latest(force_refresh=True))
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
        limit = DEFAULT_LIMIT
        if "--limit" in args:
            try:
                limit = int(args[args.index("--limit") + 1])
            except (IndexError, ValueError):
                pass
        result = asyncio.run(fetch(None, limit))

    print(json.dumps(result, ensure_ascii=False))
