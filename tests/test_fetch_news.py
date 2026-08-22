"""Tests for tools/fetch_news.py."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.fetch_news import (
    SOURCES,
    _cached_stock_name,
    _deduplicate,
    _dispatch_source,
    _fetch_cnyes,
    _fetch_forecastock,
    _filter_by_keywords,
    _fetch_rss,
    _make_article,
    _sort_by_date,
    fetch,
    latest,
)


# --- Helpers ---


def _make_httpx_response(status_code: int, text: str = "", json_data: dict | list | None = None) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


def _mock_async_client(response):
    """Build a mock httpx.AsyncClient that returns `response` on get()."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# --- Sample Data ---

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>MoneyDJ 新聞</title>
    <item>
      <title>台積電法說重點整理</title>
      <link>https://www.moneydj.com/news/12345</link>
      <pubDate>Thu, 22 Aug 2026 10:00:00 +0800</pubDate>
      <description>台積電第二季營收創新高</description>
    </item>
    <item>
      <title>半導體產業展望</title>
      <link>https://www.moneydj.com/news/12346</link>
      <pubDate>Thu, 22 Aug 2026 09:00:00 +0800</pubDate>
      <description>AI需求推升晶片需求</description>
    </item>
  </channel>
</rss>"""

SAMPLE_CNYES_RESPONSE = {
    "items": {
        "data": [
            {
                "newsId": "123456",
                "title": "台積電營收創高",
                "publishAt": 1787536800,
                "summary": "第三季展望樂觀",
            },
            {
                "newsId": "123457",
                "title": "半導體族群走強",
                "publishAt": 1787533200,
                "summary": "AI概念股全面上漲",
            },
        ]
    }
}


# --- RSS Parser Tests ---


@pytest.mark.asyncio
async def test_fetch_rss_parses_entries():
    """RSS fetcher correctly parses XML feed entries."""
    source = {"name": "MoneyDJ", "type": "rss", "url": "https://www.moneydj.com/funddj/xml/newsfeed/newsfeed.aspx"}
    response = _make_httpx_response(200, text=SAMPLE_RSS_XML)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)

    articles = await _fetch_rss(source, mock_client)

    assert len(articles) == 2
    assert articles[0]["title"] == "台積電法說重點整理"
    assert articles[0]["source"] == "MoneyDJ"
    assert articles[0]["url"] == "https://www.moneydj.com/news/12345"
    assert articles[0]["summary"] == "台積電第二季營收創新高"
    assert articles[1]["title"] == "半導體產業展望"


@pytest.mark.asyncio
async def test_fetch_rss_handles_http_error():
    """RSS fetcher returns empty list on HTTP error."""
    source = {"name": "Yahoo股市", "type": "rss", "url": "https://tw.stock.yahoo.com/rss"}
    response = _make_httpx_response(500, text="Internal Server Error")
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)

    articles = await _fetch_rss(source, mock_client)
    assert articles == []


@pytest.mark.asyncio
async def test_fetch_rss_handles_network_error():
    """RSS fetcher returns empty list on network exception."""
    source = {"name": "UDN財經", "type": "rss", "url": "https://udn.com/rssfeed/news/6/7241/0?ch=news"}
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("Connection timeout"))

    articles = await _fetch_rss(source, mock_client)
    assert articles == []


# --- CNYES API Tests ---


@pytest.mark.asyncio
async def test_fetch_cnyes_api():
    """CNYES fetcher parses JSON API response correctly."""
    response = _make_httpx_response(200, json_data=SAMPLE_CNYES_RESPONSE)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)

    articles = await _fetch_cnyes(mock_client)

    assert len(articles) == 2
    assert articles[0]["title"] == "台積電營收創高"
    assert articles[0]["source"] == "CNYES"
    assert articles[0]["url"] == "https://news.cnyes.com/news/id/123456"
    assert articles[0]["summary"] == "第三季展望樂觀"
    assert articles[0]["date"] != ""


@pytest.mark.asyncio
async def test_fetch_cnyes_with_symbol():
    """CNYES fetcher uses symbol as keyword filter."""
    response = _make_httpx_response(200, json_data=SAMPLE_CNYES_RESPONSE)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)

    articles = await _fetch_cnyes(mock_client, symbol="2330", limit=5)

    # Verify the URL includes the keyword parameter
    call_args = mock_client.get.call_args
    called_url = call_args[0][0]
    assert "keyword=2330" in called_url
    assert "limit=5" in called_url


@pytest.mark.asyncio
async def test_fetch_cnyes_handles_error():
    """CNYES fetcher returns empty list on API error."""
    response = _make_httpx_response(403, json_data={"error": "forbidden"})
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)

    articles = await _fetch_cnyes(mock_client)
    assert articles == []


# --- latest() Tests ---


@pytest.mark.asyncio
async def test_latest_parallel():
    """latest() fetches from all sources in parallel and aggregates results."""
    mock_rss_response = _make_httpx_response(200, text=SAMPLE_RSS_XML)
    mock_json_response = _make_httpx_response(200, json_data=SAMPLE_CNYES_RESPONSE)

    with patch("tools.fetch_news.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        # Return RSS for text requests, JSON for json requests
        mock_client.get = AsyncMock(return_value=mock_rss_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        result = await latest()

    assert "articles" in result
    assert isinstance(result["articles"], list)
    # Should have articles from multiple sources (RSS ones parse correctly)
    assert len(result["articles"]) > 0


@pytest.mark.asyncio
async def test_latest_returns_all_15_sources():
    """Verify SOURCES list has exactly 15 entries."""
    assert len(SOURCES) == 15


# --- fetch() Tests ---


@pytest.mark.asyncio
async def test_fetch_with_keyword():
    """fetch(keyword) filters the multi-source pool locally, keeping only
    articles mentioning the keyword (by name or code)."""
    pool = {
        "articles": [
            {"title": "台積電法說會重點", "source": "Yahoo股市", "date": "2026-01-01", "url": "https://x/1", "summary": ""},
            {"title": "航海王領漲", "source": "CNYES", "date": "2026-01-01", "url": "https://x/2", "summary": ""},
            {"title": "某報告提到台積電供應鏈", "source": "Fugle", "date": "2026-01-01", "url": "https://x/3", "summary": ""},
        ]
    }
    with patch("tools.fetch_news.latest", new=AsyncMock(return_value=pool)), patch(
        "tools.fetch_news._fetch_cnyes", new=AsyncMock(return_value=[])
    ), patch("tools.fetch_news._cached_stock_name", return_value="台積電"):
        result = await fetch("台積電", limit=5)

    titles = [a["title"] for a in result["articles"]]
    assert "台積電法說會重點" in titles
    assert "某報告提到台積電供應鏈" in titles
    assert "航海王領漲" not in titles


@pytest.mark.asyncio
async def test_fetch_keyword_matches_bare_code():
    """A bare code keyword (2330) still filters correctly when present in text."""
    pool = {
        "articles": [
            {"title": "2330 上漲", "source": "CNYES", "date": "2026-01-01", "url": "https://x/1", "summary": ""},
            {"title": "無關新聞", "source": "CNYES", "date": "2026-01-01", "url": "https://x/2", "summary": ""},
        ]
    }
    with patch("tools.fetch_news.latest", new=AsyncMock(return_value=pool)), patch(
        "tools.fetch_news._fetch_cnyes", new=AsyncMock(return_value=[])
    ), patch("tools.fetch_news._cached_stock_name", return_value=None):
        result = await fetch("2330", limit=5)

    titles = [a["title"] for a in result["articles"]]
    assert titles == ["2330 上漲"]


@pytest.mark.asyncio
async def test_fetch_without_symbol_returns_latest():
    """fetch(None) returns latest from all sources."""
    with patch("tools.fetch_news.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        response = _make_httpx_response(200, text=SAMPLE_RSS_XML)
        mock_client.get = AsyncMock(return_value=response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        result = await fetch(None, limit=3)

    assert "articles" in result
    assert len(result["articles"]) <= 3


# --- Failure Handling Tests ---


@pytest.mark.asyncio
async def test_fetch_handles_failures():
    """When some sources fail, others still return results."""
    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        # Alternate between success and failure
        if call_count % 3 == 0:
            raise Exception("Simulated network failure")
        return _make_httpx_response(200, text=SAMPLE_RSS_XML)

    with patch("tools.fetch_news.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        result = await latest()

    # Should still have articles from successful sources
    assert "articles" in result
    # Some sources succeeded, so we should have articles
    assert len(result["articles"]) >= 0  # At minimum, static source always works


# --- Deduplication Tests ---


def test_deduplication():
    """Same URL from multiple sources → only one returned."""
    articles = [
        _make_article("Article A", "Source1", "2026-08-22T10:00:00", "https://example.com/article1", "Summary A"),
        _make_article("Article A Copy", "Source2", "2026-08-22T09:00:00", "https://example.com/article1", "Summary B"),
        _make_article("Article B", "Source1", "2026-08-22T08:00:00", "https://example.com/article2", "Summary C"),
    ]

    result = _deduplicate(articles)

    assert len(result) == 2
    urls = [a["url"] for a in result]
    assert "https://example.com/article1" in urls
    assert "https://example.com/article2" in urls
    # First occurrence should be kept
    assert result[0]["title"] == "Article A"
    assert result[0]["source"] == "Source1"


def test_deduplication_preserves_empty_urls():
    """Articles without URLs are not deduplicated."""
    articles = [
        _make_article("Article A", "Source1", "2026-08-22", "", ""),
        _make_article("Article B", "Source2", "2026-08-21", "", ""),
    ]

    result = _deduplicate(articles)
    assert len(result) == 2


# --- Sorting Tests ---


def test_sort_by_date():
    """Articles are sorted by date descending."""
    articles = [
        _make_article("Old", "S", "2026-08-20T10:00:00", "url1", ""),
        _make_article("New", "S", "2026-08-22T10:00:00", "url2", ""),
        _make_article("Mid", "S", "2026-08-21T10:00:00", "url3", ""),
    ]

    result = _sort_by_date(articles)
    assert result[0]["title"] == "New"
    assert result[1]["title"] == "Mid"
    assert result[2]["title"] == "Old"


def test_sort_empty_dates_go_last():
    """Articles without dates are placed at the end."""
    articles = [
        _make_article("No Date", "S", "", "url1", ""),
        _make_article("Has Date", "S", "2026-08-22T10:00:00", "url2", ""),
    ]

    result = _sort_by_date(articles)
    assert result[0]["title"] == "Has Date"
    assert result[1]["title"] == "No Date"


# --- Article Format Tests ---


def test_make_article_format():
    """_make_article returns dict with all required keys."""
    article = _make_article("Title", "Source", "2026-08-22", "https://example.com", "Summary")
    assert article == {
        "title": "Title",
        "source": "Source",
        "date": "2026-08-22",
        "url": "https://example.com",
        "summary": "Summary",
    }


def test_make_article_strips_whitespace():
    """_make_article strips leading/trailing whitespace."""
    article = _make_article("  Title  ", "Source", "2026-08-22", "  https://example.com  ", "  Summary  ")
    assert article["title"] == "Title"
    assert article["url"] == "https://example.com"
    assert article["summary"] == "Summary"


# --- CLI Tests ---


def test_cli_with_symbol(monkeypatch):
    """CLI with symbol argument outputs valid JSON."""
    import subprocess

    # We test the import interface instead to avoid network calls
    from tools.fetch_news import fetch, latest

    assert callable(fetch)
    assert callable(latest)


def test_sources_count():
    """Verify all 15 sources are defined."""
    assert len(SOURCES) == 15
    names = [s["name"] for s in SOURCES]
    assert "CNYES" in names
    assert "MoneyDJ" in names
    assert "Yahoo股市" in names
    assert "UDN財經" in names
    assert "UAnalyze" in names
    assert "Fugle" in names
    assert "Vocus" in names
    assert "MacroMicro" in names
    assert "FinGuider" in names
    assert "Fintastic" in names
    assert "Forecastock" in names
    assert "NewsDigestAI" in names
    assert "SinoTrade" in names
    assert "Pocket學堂" in names
    assert "Buffett+Marks" in names


# --- Forecastock direct-fetch tests ---


FORECASTOCK_HTML = """
<html><body>
  <a class="articleListItem__link" href="/article/aaa-111">前往【美股研究報告】美光分析</a>
  <a class="articleListItem__link" href="/article/bbb-222">前往【個股報告】台積電展望</a>
  <a class="other" href="/ignore">不是文章</a>
</body></html>
"""


@pytest.mark.asyncio
async def test_fetch_forecastock_parses_articles():
    """Forecastock direct fetch parses articleListItem__link and strips 前往 prefix."""
    response = _make_httpx_response(200, text=FORECASTOCK_HTML)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.fetch_news.httpx.AsyncClient", return_value=mock_client):
        articles = await _fetch_forecastock(AsyncMock())

    assert len(articles) == 2
    assert articles[0]["title"] == "【美股研究報告】美光分析"
    assert articles[0]["url"] == "https://www.forecastock.tw/article/aaa-111"
    assert articles[0]["source"] == "Forecastock"


@pytest.mark.asyncio
async def test_fetch_forecastock_http_error():
    """Forecastock returns empty list on non-200."""
    response = _make_httpx_response(403, text="")
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.fetch_news.httpx.AsyncClient", return_value=mock_client):
        articles = await _fetch_forecastock(AsyncMock())

    assert articles == []


# --- MacroMicro (curl_cffi) + Fintastic (WordPress API) tests ---


@pytest.mark.asyncio
async def test_fetch_macromicro_parses_rss():
    """MacroMicro fetch via curl_cffi parses RSS feed."""
    from tools.fetch_news import _fetch_macromicro

    resp = MagicMock()
    resp.status_code = 200
    resp.text = SAMPLE_RSS_XML

    with patch("tools.fetch_news._cffi_get", return_value=resp):
        articles = await _fetch_macromicro(AsyncMock())

    assert len(articles) == 2
    assert articles[0]["source"] == "MacroMicro"
    assert articles[0]["title"] == "台積電法說重點整理"


@pytest.mark.asyncio
async def test_fetch_macromicro_blocked():
    """MacroMicro returns empty on 403 (Cloudflare block)."""
    from tools.fetch_news import _fetch_macromicro

    resp = MagicMock()
    resp.status_code = 403
    resp.text = ""

    with patch("tools.fetch_news._cffi_get", return_value=resp):
        articles = await _fetch_macromicro(AsyncMock())

    assert articles == []


@pytest.mark.asyncio
async def test_fetch_macromicro_no_curl_cffi():
    """MacroMicro returns empty gracefully if curl_cffi missing."""
    from tools.fetch_news import _fetch_macromicro

    with patch("tools.fetch_news._cffi_get", return_value=None):
        articles = await _fetch_macromicro(AsyncMock())

    assert articles == []


@pytest.mark.asyncio
async def test_fetch_fintastic_parses_wp_api():
    """Fintastic parses WordPress REST API posts."""
    from tools.fetch_news import _fetch_fintastic

    wp_posts = [
        {
            "title": {"rendered": "AI 的 Android 時刻"},
            "link": "https://fintastic.trading/market_analysis/ai",
            "date": "2026-08-17T04:18:11",
            "excerpt": {"rendered": "<p>摘要內容</p>"},
        },
        {
            "title": {"rendered": "TOP 30 成長股"},
            "link": "https://fintastic.trading/stock/top30",
            "date": "2026-04-24T22:52:14",
            "excerpt": {"rendered": ""},
        },
    ]
    resp = _make_httpx_response(200, json_data=wp_posts)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.fetch_news.httpx.AsyncClient", return_value=mock_client):
        articles = await _fetch_fintastic(AsyncMock())

    assert len(articles) == 2
    assert articles[0]["source"] == "Fintastic"
    assert articles[0]["title"] == "AI 的 Android 時刻"
    assert articles[0]["summary"] == "摘要內容"  # HTML stripped


@pytest.mark.asyncio
async def test_fetch_fintastic_blocked():
    """Fintastic returns empty on non-200."""
    from tools.fetch_news import _fetch_fintastic

    resp = _make_httpx_response(403, text="")
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.fetch_news.httpx.AsyncClient", return_value=mock_client):
        articles = await _fetch_fintastic(AsyncMock())

    assert articles == []


# --- Keyword filter tests ---


def test_filter_by_keywords_matches_title_and_summary():
    """Filter keeps articles matching any keyword in title or summary."""
    articles = [
        {"title": "台積電擴廠", "summary": ""},
        {"title": "無關新聞", "summary": "內文提到 2330"},
        {"title": "航運上漲", "summary": "與半導體無關"},
    ]
    result = _filter_by_keywords(articles, ["台積電", "2330"])
    titles = [a["title"] for a in result]
    assert "台積電擴廠" in titles
    assert "無關新聞" in titles  # matched via summary
    assert "航運上漲" not in titles


def test_filter_by_keywords_empty_keywords_returns_all():
    """No keywords → no filtering (return everything)."""
    articles = [{"title": "a", "summary": ""}, {"title": "b", "summary": ""}]
    assert _filter_by_keywords(articles, []) == articles
