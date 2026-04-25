"""Tests for news parser selector fallback logic."""

import json

import pytest
from bs4 import BeautifulSoup

from analysis_bot.services.news_parser import NewsParser


@pytest.fixture
def parser():
    return NewsParser()


# ── CNYES ────────────────────────────────────────────────────────────────


def test_cnyes_parser_next_data(parser):
    """CNYES parser extracts content from __NEXT_DATA__ JSON."""
    article_content = "台積電第四季營收創新高，超越市場預期。法人看好明年展望，目標價上調至一千元。半導體產業持續成長，AI 需求帶動先進製程訂單。"
    nd_json = json.dumps({"props": {"pageProps": {"newsDetail": {"content": article_content}}}})
    html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{nd_json}</script></body></html>'
    soup = BeautifulSoup(html, "html.parser")
    result = parser.cnyes_news_parser(soup)
    assert "台積電" in result
    assert "營收" in result


def test_cnyes_parser_next_data_html_content(parser):
    """CNYES parser strips HTML tags from __NEXT_DATA__ content."""
    html = """<html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"newsDetail":{"content":"<p>台積電第四季營收創新高，超越市場預期。</p><p>法人看好明年展望，目標價上調至一千元。半導體產業持續成長。</p>"}}}}
    </script></body></html>"""
    soup = BeautifulSoup(html, "html.parser")
    result = parser.cnyes_news_parser(soup)
    assert "<p>" not in result
    assert "台積電" in result


def test_cnyes_parser_itemprop_fallback(parser):
    """CNYES parser falls back to itemprop articleBody."""
    content = "A" * 150  # > 100 chars
    html = f'<html><body><div itemprop="articleBody">{content}</div></body></html>'
    soup = BeautifulSoup(html, "html.parser")
    result = parser.cnyes_news_parser(soup)
    assert result == content


def test_cnyes_parser_og_fallback(parser):
    """CNYES parser falls back to og:description."""
    html = '<html><head><meta property="og:description" content="台積電法說會重點摘要"/></head><body></body></html>'
    soup = BeautifulSoup(html, "html.parser")
    result = parser.cnyes_news_parser(soup)
    assert "台積電" in result


def test_cnyes_parser_empty(parser):
    """CNYES parser returns empty string for empty page."""
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    result = parser.cnyes_news_parser(soup)
    assert result == ""


# ── Vocus ────────────────────────────────────────────────────────────────


def test_vocus_parser_next_data(parser):
    """Vocus parser extracts content from __NEXT_DATA__ JSON."""
    html = """<html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"parsedArticle":{"content":"<p>投資心法分享：長期持有的重要性，複利效果需要時間才能顯現。定期定額是最適合一般投資人的策略。</p>"}}}}
    </script></body></html>"""
    soup = BeautifulSoup(html, "html.parser")
    result = parser.vocus_news_parser(soup)
    assert "投資心法" in result
    assert "<p>" not in result


def test_vocus_parser_og_fallback(parser):
    """Vocus parser falls back to og:description."""
    html = '<html><head><meta property="og:description" content="方格子精選投資文章"/></head><body></body></html>'
    soup = BeautifulSoup(html, "html.parser")
    result = parser.vocus_news_parser(soup)
    assert "方格子" in result


def test_vocus_parser_empty(parser):
    """Vocus parser returns empty string for empty page."""
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    result = parser.vocus_news_parser(soup)
    assert result == ""


# ── Generic ──────────────────────────────────────────────────────────────


def test_generic_parser_article_tag(parser):
    """Generic parser extracts from <article> tag."""
    content = "B" * 150
    html = f"<html><body><article>{content}</article></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    result = parser._generic_news_parser(soup)
    assert result == content


def test_generic_parser_next_data(parser):
    """Generic parser extracts from __NEXT_DATA__."""
    long_content = "A" * 100 + "文章內容測試"
    nd_json = json.dumps({"props": {"pageProps": {"article": {"content": long_content}}}})
    html = f'<html><body><script id="__NEXT_DATA__" type="application/json">{nd_json}</script></body></html>'
    soup = BeautifulSoup(html, "html.parser")
    result = parser._generic_news_parser(soup)
    assert "文章內容" in result


def test_generic_parser_og_fallback(parser):
    """Generic parser falls back to og:description."""
    html = '<html><head><meta property="og:description" content="測試描述"/></head><body></body></html>'
    soup = BeautifulSoup(html, "html.parser")
    result = parser._generic_news_parser(soup)
    assert result == "測試描述"


# ── cnyes_quote_scraper ──────────────────────────────────────────────────


def test_cnyes_quote_next_data():
    """cnyes_quote_scraper extracts from __NEXT_DATA__."""
    from analysis_bot.services.cnyes_quote_scraper import _parse_quote_page

    html = """<html><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"quote":{"name":"台積電","price":895.0,"change":-5.0,"changePercent":-0.56}}}}
    </script></body></html>"""
    result = _parse_quote_page(html, "2330")
    assert result is not None
    assert result["name"] == "台積電"
    assert result["price"] == 895.0
    assert result["change"] == -5.0
    assert result["change_pct"] == -0.56


def test_cnyes_quote_h2h3_fallback():
    """cnyes_quote_scraper falls back to h2/h3 parsing."""
    from analysis_bot.services.cnyes_quote_scraper import _parse_quote_page

    html = """<html><body>
    <h2>台積電2330</h2>
    <h3>895</h3>
    <span>-5.00 -0.56%</span>
    </body></html>"""
    result = _parse_quote_page(html, "2330")
    assert result is not None
    assert result["price"] == 895.0


def test_cnyes_quote_og_title_fallback():
    """cnyes_quote_scraper uses og:title for stock name when h1/h2 missing."""
    from analysis_bot.services.cnyes_quote_scraper import _parse_quote_page

    html = """<html><head>
    <meta property="og:title" content="台積電2330 即時報價"/>
    </head><body>
    <h3>895</h3>
    </body></html>"""
    result = _parse_quote_page(html, "2330")
    assert result is not None
    assert result["name"] == "台積電"
    assert result["price"] == 895.0
