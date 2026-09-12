"""Tests for tools/analysis/summarize_document.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tools.analysis.summarize_document import (
    _extract_text_from_html,
    _fetch_url,
    _summarize_with_agent,
    summarize,
)


# --- Helpers ---

SAMPLE_HTML = b"""
<html>
<head><title>Test Article Title</title></head>
<body>
<nav>Navigation</nav>
<article>
<p>This is the main article content. It has enough text to pass the 200-char threshold.
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt
ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation.</p>
</article>
<footer>Footer content</footer>
</body>
</html>
"""

SAMPLE_HTML_NO_ARTICLE = b"""
<html>
<head><title>Page Title</title></head>
<body>
<p>Body content that is long enough to be extracted as text for summarization purposes.
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt
ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation.</p>
</body>
</html>
"""

SAMPLE_HTML_SHORT = b"""
<html>
<head><title>Short</title></head>
<body><p>Too short.</p></body>
</html>
"""


def _make_httpx_response(status_code: int, content: bytes, content_type: str = "text/html") -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.headers = {"content-type": content_type}

    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None

    return resp


def _mock_async_client(response):
    """Build a mock httpx.AsyncClient that returns `response` on get()."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# --- _extract_text_from_html tests ---


def test_extract_text_from_html():
    """Extract title and body text from HTML."""
    title, text = _extract_text_from_html(SAMPLE_HTML_NO_ARTICLE)
    assert title == "Page Title"
    assert "Body content" in text
    assert len(text) > 50


def test_extract_text_from_html_article():
    """Prefer article tag content over body."""
    title, text = _extract_text_from_html(SAMPLE_HTML)
    assert title == "Test Article Title"
    assert "main article content" in text
    # Nav and footer should be removed
    assert "Navigation" not in text
    assert "Footer content" not in text


def test_extract_text_from_html_og_title():
    """Extract title from og:title meta tag."""
    html = b"""
    <html>
    <head>
    <meta property="og:title" content="OG Title Here" />
    </head>
    <body><p>Some body content that is reasonably long for testing purposes here.</p></body>
    </html>
    """
    title, text = _extract_text_from_html(html)
    assert title == "OG Title Here"


# --- summarize tests ---


@pytest.mark.asyncio
async def test_summarize_html_success():
    """Successful HTML summarization returns expected JSON structure."""
    mock_resp = _make_httpx_response(200, SAMPLE_HTML, "text/html; charset=utf-8")
    mock_client = _mock_async_client(mock_resp)

    with patch("tools.analysis.summarize_document.httpx.AsyncClient", return_value=mock_client):
        with patch("tools.analysis.summarize_document._summarize_with_agent", new_callable=AsyncMock) as mock_agent:
            mock_agent.return_value = "這是一篇關於測試的文章摘要。"

            result = await summarize("https://example.com/article")

    assert result["title"] == "Test Article Title"
    assert result["summary"] == "這是一篇關於測試的文章摘要。"
    assert result["source_url"] == "https://example.com/article"
    assert "error" not in result


@pytest.mark.asyncio
async def test_summarize_pdf_success():
    """Successful PDF summarization returns expected JSON structure."""
    fake_pdf_text = "A" * 300  # Long enough text
    mock_resp = _make_httpx_response(200, b"fake-pdf-bytes", "application/pdf")
    mock_client = _mock_async_client(mock_resp)

    with patch("tools.analysis.summarize_document.httpx.AsyncClient", return_value=mock_client):
        with patch("tools.analysis.summarize_document._extract_text_from_pdf") as mock_pdf:
            mock_pdf.return_value = ("PDF Report Title", fake_pdf_text)
            with patch("tools.analysis.summarize_document._summarize_with_agent", new_callable=AsyncMock) as mock_agent:
                mock_agent.return_value = "PDF 摘要內容。"

                result = await summarize("https://example.com/report.pdf")

    assert result["title"] == "PDF Report Title"
    assert result["summary"] == "PDF 摘要內容。"
    assert result["source_url"] == "https://example.com/report.pdf"


@pytest.mark.asyncio
async def test_summarize_url_not_found():
    """HTTP 404 returns error dict."""
    mock_resp = _make_httpx_response(404, b"Not Found")
    mock_client = _mock_async_client(mock_resp)

    with patch("tools.analysis.summarize_document.httpx.AsyncClient", return_value=mock_client):
        result = await summarize("https://example.com/missing")

    assert "error" in result
    assert "404" in result["error"]


@pytest.mark.asyncio
async def test_summarize_url_unreachable():
    """Network error returns error dict."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("tools.analysis.summarize_document.httpx.AsyncClient", return_value=mock_client):
        result = await summarize("https://unreachable.invalid/page")

    assert "error" in result
    assert "無法存取" in result["error"]


@pytest.mark.asyncio
async def test_summarize_empty_url():
    """Empty URL returns error."""
    result = await summarize("")
    assert "error" in result
    assert "請輸入 URL" in result["error"]


@pytest.mark.asyncio
async def test_summarize_invalid_url():
    """Invalid URL (no scheme) returns error."""
    result = await summarize("not-a-url")
    assert "error" in result
    assert "無效的 URL" in result["error"]


@pytest.mark.asyncio
async def test_summarize_insufficient_text():
    """Page with <50 chars of extracted text returns error."""
    mock_resp = _make_httpx_response(200, SAMPLE_HTML_SHORT, "text/html")
    mock_client = _mock_async_client(mock_resp)

    with patch("tools.analysis.summarize_document.httpx.AsyncClient", return_value=mock_client):
        result = await summarize("https://example.com/short")

    assert "error" in result
    assert "無法擷取足夠的文字內容" in result["error"]


@pytest.mark.asyncio
async def test_summarize_agent_fallback():
    """When agent fails, falls back to truncated text."""
    mock_resp = _make_httpx_response(200, SAMPLE_HTML, "text/html; charset=utf-8")
    mock_client = _mock_async_client(mock_resp)

    with patch("tools.analysis.summarize_document.httpx.AsyncClient", return_value=mock_client):
        with patch("agent.bridge.AntigravityCLIBridge.send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = RuntimeError("Agent unavailable")

            result = await summarize("https://example.com/article")

    # Should still return a result (fallback text, not error)
    assert "title" in result
    assert "summary" in result
    assert "source_url" in result
    assert "error" not in result


@pytest.mark.asyncio
async def test_summarize_pdf_by_content_type():
    """PDF detected by content-type header (not just URL extension)."""
    fake_pdf_text = "B" * 300
    mock_resp = _make_httpx_response(200, b"pdf-bytes", "application/pdf; charset=binary")
    mock_client = _mock_async_client(mock_resp)

    with patch("tools.analysis.summarize_document.httpx.AsyncClient", return_value=mock_client):
        with patch("tools.analysis.summarize_document._extract_text_from_pdf") as mock_pdf:
            mock_pdf.return_value = ("Financial Report", fake_pdf_text)
            with patch("tools.analysis.summarize_document._summarize_with_agent", new_callable=AsyncMock) as mock_agent:
                mock_agent.return_value = "Financial summary."

                # URL does NOT end in .pdf but content-type is application/pdf
                result = await summarize("https://example.com/download?id=123")

    assert result["title"] == "Financial Report"
    mock_pdf.assert_called_once()


@pytest.mark.asyncio
async def test_summarize_whitespace_url():
    """URL with leading/trailing whitespace is trimmed."""
    mock_resp = _make_httpx_response(200, SAMPLE_HTML, "text/html")
    mock_client = _mock_async_client(mock_resp)

    with patch("tools.analysis.summarize_document.httpx.AsyncClient", return_value=mock_client):
        with patch("tools.analysis.summarize_document._summarize_with_agent", new_callable=AsyncMock) as mock_agent:
            mock_agent.return_value = "Summary."

            result = await summarize("  https://example.com/article  ")

    assert result["source_url"] == "https://example.com/article"
