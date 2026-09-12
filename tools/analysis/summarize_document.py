"""summarize_document — URL/PDF 文件摘要
用法: python tools/analysis/summarize_document.py URL
回傳: JSON {"title": str, "summary": str, "source_url": str}
"""

import asyncio
import json
import logging
import os
import sys
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

# 直接跑 python tools/analysis/summarize_document.py 時，repo 根不在 sys.path，
# 補上以便 import agent.bridge（AI 摘要）。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
MAX_TEXT_LENGTH = 15000  # chars to send to agent (avoid token overflow)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) StockBot/1.0"


async def _fetch_url(url: str) -> tuple[bytes, str]:
    """Fetch URL content. Returns (content_bytes, content_type)."""
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "")
        return r.content, content_type


def _extract_text_from_html(html_bytes: bytes) -> tuple[str, str]:
    """Extract title and main text from HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_bytes, "html.parser")

    # Extract title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    elif soup.find("meta", property="og:title"):
        title = soup.find("meta", property="og:title").get("content", "")

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
        tag.decompose()

    # Try article body first
    text = ""
    for selector in ["article", "[itemprop='articleBody']", "main", ".post-content", ".article-content"]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 200:
                break

    # Fallback to body
    if len(text) < 200:
        body = soup.find("body")
        if body:
            text = body.get_text(separator="\n", strip=True)

    return title, text


def _extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, str]:
    """Extract text from PDF bytes."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        # Fallback: try pdfplumber
        try:
            import pdfplumber
            import io

            text_parts = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages[:20]:  # limit pages
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            text = "\n".join(text_parts)
            title = text[:100].split("\n")[0] if text else "PDF Document"
            return title, text
        except ImportError:
            return "PDF Document", "[PDF extraction requires PyMuPDF or pdfplumber]"

    import io

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_parts = []
    for page in doc[:20]:  # limit pages
        text_parts.append(page.get_text())
    doc.close()
    text = "\n".join(text_parts)
    title = text[:100].split("\n")[0] if text else "PDF Document"
    return title, text


async def _summarize_with_agent(text: str, title: str) -> str:
    """Use AgentBridge to generate summary."""
    from agent.bridge import AntigravityCLIBridge

    bridge = AntigravityCLIBridge()

    # Truncate to avoid token overflow
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH] + "\n...(truncated)"

    prompt = (
        f"請用繁體中文摘要以下文章，提供 3-5 個重點：\n\n"
        f"標題: {title}\n\n"
        f"{text}"
    )

    try:
        summary = await bridge.send(prompt)
        return summary
    except (TimeoutError, RuntimeError) as e:
        logger.warning("Agent summarization failed: %s", e)
        # Fallback: first 500 chars as summary
        return text[:500] + "..." if len(text) > 500 else text


async def summarize(url: str) -> dict:
    """Summarize a document from URL.

    Args:
        url: Web page or PDF URL

    Returns:
        dict with title, summary, source_url on success;
        dict with error key on failure.
    """
    url = url.strip()
    if not url:
        return {"error": "請輸入 URL"}

    # Validate URL
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return {"error": f"無效的 URL: {url}"}

    try:
        content, content_type = await _fetch_url(url)
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: 無法存取 {url}"}
    except Exception as e:
        return {"error": f"無法存取 {url}: {e}"}

    # Determine type and extract text
    is_pdf = "pdf" in content_type.lower() or url.lower().endswith(".pdf")

    if is_pdf:
        title, text = _extract_text_from_pdf(content)
    else:
        title, text = _extract_text_from_html(content)

    if not text or len(text) < 50:
        return {"error": f"無法擷取足夠的文字內容（{len(text)} chars）"}

    # Summarize
    summary = await _summarize_with_agent(text, title)

    return {
        "title": title or "Untitled",
        "summary": summary,
        "source_url": url,
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "用法: python tools/analysis/summarize_document.py URL"}, ensure_ascii=False))
        sys.exit(1)

    url = args[0]
    result = asyncio.run(summarize(url))
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
