import asyncio
import html
import logging
import re
from datetime import datetime
from urllib.parse import quote

import aiohttp
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from ..config import get_settings
from .http import http_retry

settings = get_settings()


class NewsParser:
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Mapping sites to parser functions
        self.parser_dict = {
            "udn": self.udn_news_parser,
            "cnyes": self.cnyes_news_parser,
            "moneydj": self.moneyDJ_news_parser,
            "uanalyze": self.uanalyze_news_parser,
            "fugle": self.fugle_news_parser,
            "vocus": self.vocus_news_parser,
            "sinotrade": self.sinotrade_news_parser,
            "pocket.tw": self.pocket_news_parser,
            "yahoo": self.yahoo_tw_news_parser,
            "cqd.tw": self.newsdigestai_news_parser,
            "macromicro": self.macromicro_news_parser,
            "finguider": self.finguider_news_parser,
            "fintastic": self.fintastic_news_parser,
            "forecastock": self.forecastock_news_parser,
        }
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        self.session = None

    async def init_session(self):
        if not self.session or self.session.closed:
            from .http import create_session

            timeout = aiohttp.ClientTimeout(total=30)
            self.session = create_session(headers=self.headers, timeout=timeout)
        self.logger.info("NewsParser init session done")

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

    def clean_all(self, text):
        text = html.unescape(text)
        text = re.sub(r"<[^>]+>", "", text)
        return text

    def _clean_html_for_ai(self, soup: BeautifulSoup) -> str:
        """Remove scripts, styles, and other non-content elements to save AI tokens."""
        if not soup:
            return ""
        # Create a copy to avoid modifying the original soup
        temp_soup = BeautifulSoup(str(soup), "html.parser")
        for tag in temp_soup(
            ["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]
        ):
            tag.decompose()
        return temp_soup.get_text(separator="\n", strip=True)

    @http_retry
    async def rss_parser(self, url: str) -> list[dict]:
        results = []
        try:
            if not self.session or self.session.closed:
                await self.init_session()

            ssl_verify = False if "moneydj.com" in url else None
            async with self.session.get(url, ssl=ssl_verify) as resp:
                raw = await resp.read()
                # Try UTF-8 first, fallback to detected or latin-1
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode(resp.get_encoding() or "latin-1", errors="replace")
            feed = feedparser.parse(text)
            results = [
                {
                    "title": entry.title,
                    "url": entry.link,
                    "description": entry.description if hasattr(entry, "description") else None,
                    "pubTime": (
                        dateparser.parse(entry.published) if hasattr(entry, "published") else None
                    ),
                    "src": "rss",
                }
                for entry in feed.entries
            ]
        except Exception as e:
            self.logger.error(f"RSS parse error {url}: {e}")
        return results

    @http_retry
    async def news_request(self, url: str, params: dict = None) -> BeautifulSoup:
        try:
            if not self.session or self.session.closed:
                await self.init_session()

            async with self.session.get(url, params=params) as resp:
                resp.raise_for_status()
                raw = await resp.read()
                # Try UTF-8 first, fallback to detected or latin-1
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode(resp.get_encoding() or "latin-1", errors="replace")
                return BeautifulSoup(text, "html.parser")
        except Exception as e:
            self.logger.error(f"HTTP request error {url}: {e}")
            return None

    def moneyDJ_news_parser(self, soup) -> str:
        try:
            article = soup.find("article")
            if not article:
                return ""
            paragraphs = article.find_all("p")
            content = "\n".join(
                p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
            )
            return content
        except Exception as e:
            self.logger.warning("moneyDJ_news_parser failed: %s", e)
            return ""

    def udn_news_parser(self, soup) -> str:
        try:
            section = soup.find("section", class_="article-body__editor")
            if not section:
                return ""
            # Remove ad blocks before extracting text
            for ad in section.select(".edn-ads--inlineAds, .coverad, style, script"):
                ad.decompose()
            paragraphs = section.find_all("p")
            content = "\n".join(
                p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
            )
            return content
        except Exception as e:
            self.logger.warning("udn_news_parser failed: %s", e)
            return ""

    def cnyes_news_parser(self, soup) -> str:
        try:
            import json as _json

            # Primary: __NEXT_DATA__ JSON (most reliable for Next.js sites)
            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                try:
                    data = _json.loads(nd.string)
                    props = data.get("props", {}).get("pageProps", {})
                    detail = props.get("newsDetail") or props.get("article") or {}
                    content = detail.get("content", "")
                    if content and len(content) > 50:
                        if "<" in content:
                            return BeautifulSoup(content, "html.parser").get_text(
                                separator="\n", strip=True
                            )
                        return content
                except (ValueError, KeyError):
                    pass

            # Secondary: common content containers (avoid CSS-in-JS hash classes)
            for sel in ("div[itemprop='articleBody']", "article", "main"):
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text) > 100:
                        return text

            # Fallback: og:description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            return ""
        except Exception as e:
            self.logger.warning("cnyes_news_parser failed: %s", e)
            return ""

    def uanalyze_news_parser(self, soup) -> str:
        """UAnalyze: main article in #ua-article-content with .prose paragraphs."""
        try:
            # Primary: main article content container
            container = soup.select_one("#ua-article-content, .ua-article-content")
            if container:
                paragraphs = container.find_all("p")
                if paragraphs:
                    content = "\n".join(
                        p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
                    )
                    if content and len(content) > 50:
                        return content
                # If no <p> tags, try getting all text
                text = container.get_text(separator="\n", strip=True)
                if text and len(text) > 50:
                    return text
            # Secondary: try .article-content (older layout)
            container = soup.select_one(".article-content")
            if container:
                paragraphs = container.find_all("p")
                if paragraphs:
                    content = "\n".join(
                        p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
                    )
                    if content and len(content) > 50:
                        return content
            # Fallback: og:description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            return ""
        except Exception as e:
            self.logger.warning("uanalyze_news_parser failed: %s", e)
            return ""

    def fugle_news_parser(self, soup) -> str:
        """Fugle: Next.js SSR – full article rendered in prose div."""
        try:
            # Primary: prose container has full article body
            prose = soup.select_one('div.prose, [class*="prose"]')
            if prose:
                text = prose.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return text
            # Secondary: __NEXT_DATA__ may contain article content
            import json as _json

            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                data = _json.loads(nd.string)
                props = data.get("props", {}).get("pageProps", {})
                post = props.get("post") or props.get("article") or {}
                for field in ("html", "content", "plaintext", "body"):
                    raw = post.get(field, "")
                    if raw and len(raw) > 100:
                        if "<" in raw:
                            return BeautifulSoup(raw, "html.parser").get_text(
                                separator="\n", strip=True
                            )
                        return raw
            # Fallback: meta description
            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content"):
                return desc["content"]
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            return ""
        except Exception as e:
            self.logger.warning("fugle_news_parser failed: %s", e)
            return ""

    def vocus_news_parser(self, soup) -> str:
        """Vocus: Next.js SSR, article content available in __NEXT_DATA__ -> parsedArticle.content."""
        try:
            import json

            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                data = json.loads(nd.string)
                props = data.get("props", {}).get("pageProps", {})
                # Primary: parsedArticle.content (plain text, may contain HTML tags)
                parsed = props.get("parsedArticle", {})
                if isinstance(parsed, dict):
                    content = parsed.get("content", "")
                    if content and len(content) > 50:
                        # Strip HTML tags if present
                        if "<" in content:
                            from bs4 import BeautifulSoup as BS

                            content = BS(content, "html.parser").get_text(
                                separator="\n", strip=True
                            )
                        return content
                # Secondary: fallback article content (HTML)
                fallback = props.get("fallback", {})
                if isinstance(fallback, dict):
                    for key, val in fallback.items():
                        if "article" in key.lower() and isinstance(val, dict):
                            art_content = val.get("article", {}).get("content", "")
                            if art_content:
                                if "<" in art_content:
                                    from bs4 import BeautifulSoup as BS

                                    return BS(art_content, "html.parser").get_text(
                                        separator="\n", strip=True
                                    )
                                return art_content
            # Fallback: og:description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            return ""
        except Exception as e:
            self.logger.warning("vocus_news_parser failed: %s", e)
            return ""

    def sinotrade_news_parser(self, soup) -> str:
        """SinoTrade RichClub: Next.js SSR – full content in __NEXT_DATA__ -> post.content.all."""
        try:
            import json as _json

            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                data = _json.loads(nd.string)
                post = data.get("props", {}).get("pageProps", {}).get("post", {})
                # content.all contains full HTML article
                content_obj = post.get("content", {})
                if isinstance(content_obj, dict):
                    raw = content_obj.get("all", "")
                    if raw and len(raw) > 50:
                        return BeautifulSoup(raw, "html.parser").get_text(
                            separator="\n", strip=True
                        )
                # Try paragraph (shorter summary, ~200 chars) as secondary
                paragraph = post.get("paragraph", "")
                if paragraph and len(paragraph) > 30:
                    return paragraph
            # Fallback: og:description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content"):
                return desc["content"]
            return ""
        except Exception as e:
            self.logger.warning("sinotrade_news_parser failed: %s", e)
            return ""

    def pocket_news_parser(self, soup) -> str:
        """Pocket: Django template – full article HTML in data-content attribute."""
        try:
            # Primary: article content is stored as HTML-encoded string in data-content attr
            el = soup.find(attrs={"data-content": True})
            if el:
                raw = html.unescape(el["data-content"])
                if raw and len(raw) > 100:
                    content = BeautifulSoup(raw, "html.parser").get_text(separator="\n", strip=True)
                    if content and len(content) > 80:
                        return content
            # Secondary: try common containers
            for sel in (
                "article",
                ".article-content",
                ".post-content",
                ".invest-content",
            ):
                container = soup.select_one(sel)
                if container:
                    text = container.get_text(separator="\n", strip=True)
                    if len(text) > 100:
                        return text
            # Fallback: og:description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content"):
                return desc["content"]
            return ""
        except Exception as e:
            self.logger.warning("pocket_news_parser failed: %s", e)
            return ""

    def yahoo_tw_news_parser(self, soup) -> str:
        """Yahoo TW Stock: SSR – article body in caas-body div."""
        try:
            # Primary: Yahoo uses caas-body for article content
            body = soup.select_one('[class*="caas-body"]')
            if body:
                text = body.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return text
            # Secondary: article-body or similar
            for sel in ("article", '[class*="article-body"]', ".story-body", "main"):
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text) > 100:
                        return text
            # Fallback: og:description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            return ""
        except Exception as e:
            self.logger.warning("yahoo_tw_news_parser failed: %s", e)
            return ""

    def newsdigestai_news_parser(self, soup) -> str:
        """NewsDigest AI: extract article content from page."""
        try:
            # Try common article containers
            for sel in (
                "article",
                ".article-content",
                ".post-content",
                "main .content",
                "main",
            ):
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text) > 100:
                        return text
            # Fallback: og:description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content"):
                return desc["content"]
            return ""
        except Exception as e:
            self.logger.warning("newsdigestai_news_parser failed: %s", e)
            return ""

    def macromicro_news_parser(self, soup) -> str:
        """Macromicro (財經M平方): SSR blog posts."""
        try:
            # Primary: post-content or article container
            for sel in (
                '[class*="post-content"]',
                '[class*="article-content"]',
                "article",
                ".blog-content",
                "main",
            ):
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text) > 100:
                        return text
            # Fallback: og:description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content"):
                return desc["content"]
            return ""
        except Exception as e:
            self.logger.warning("macromicro_news_parser failed: %s", e)
            return ""

    def finguider_news_parser(self, soup) -> str:
        """FinGuider (瑞星財經): Vue SPA – no SSR, use generic fallback or API content."""
        # FinGuider is a pure Vue SPA; article pages have no SSR content.
        # Full content is obtained via get_finguider_report() API which returns
        # content directly. This parser is only called as fallback from
        # fetch_news_content() for FinGuider URLs – it will fall through to
        # _generic_news_parser which handles og:description.
        try:
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content"):
                return desc["content"]
            return ""
        except Exception as e:
            self.logger.warning("finguider_news_parser failed: %s", e)
            return ""

    def fintastic_news_parser(self, soup) -> str:
        """Fintastic: SSR blog – extract from article/main."""
        try:
            for sel in ("article", ".post-content", ".article-content", "main"):
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text) > 100:
                        return text
            # Fallback: og:description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content"):
                return desc["content"]
            return ""
        except Exception as e:
            self.logger.warning("fintastic_news_parser failed: %s", e)
            return ""

    def forecastock_news_parser(self, soup) -> str:
        """Forecastock: SSR – article tag contains full report."""
        try:
            article = soup.find("article")
            if article:
                text = article.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return text
            # Try other containers
            for sel in (".article-content", ".post-content", "main"):
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text) > 100:
                        return text
            # Fallback: og:description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content"):
                return desc["content"]
            return ""
        except Exception as e:
            self.logger.warning("forecastock_news_parser failed: %s", e)
            return ""

    def _generic_news_parser(self, soup) -> str:
        """Generic fallback parser: try common article patterns, then meta tags."""
        try:
            # Try common article containers
            for sel in (
                "article",
                '[role="main"]',
                "main",
                ".post-content",
                ".article-content",
                ".entry-content",
            ):
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text) > 100:
                        return text
            # Try __NEXT_DATA__ (common in Next.js sites)
            import json as _json

            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                data = _json.loads(nd.string)
                props = data.get("props", {}).get("pageProps", {})
                for key in ("article", "post", "data", "content"):
                    obj = props.get(key, {})
                    if isinstance(obj, dict):
                        for field in ("content", "body", "html", "plaintext"):
                            raw = obj.get(field, "")
                            if raw and len(raw) > 80:
                                if "<" in raw:
                                    return BeautifulSoup(raw, "html.parser").get_text(
                                        separator="\n", strip=True
                                    )
                                return raw
                    elif isinstance(obj, str) and len(obj) > 80:
                        return obj
            # Fallback: og:description / meta description
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            desc = soup.find("meta", attrs={"name": "description"})
            if desc and desc.get("content"):
                return desc["content"]
            return ""
        except Exception as e:
            self.logger.warning("_generic_news_parser failed: %s", e)
            return ""

    async def _fetch_finguider_content(self, url: str) -> str | None:
        """FinGuider: pure SPA – fetch full article via JSON API by ID."""
        try:
            # Extract article ID from URL like .../ArticleIndex/2723
            import re as _re

            m = _re.search(r"ArticleIndex/(\d+)", url)
            if not m:
                return None
            art_id = m.group(1)
            api_url = f"https://finguider.cc/Api/article/{art_id}/"
            if not self.session or self.session.closed:
                await self.init_session()
            async with self.session.get(api_url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
            raw = data.get("content", "")
            if raw:
                return self.clean_all(raw)
            return data.get("describe", "") or None
        except Exception as e:
            self.logger.error(f"FinGuider API content error: {e}")
            return None

    async def fetch_news_content(self, url: str, ai_service=None) -> str:
        """Fetch and parse full article content from a news URL."""
        # FinGuider: pure SPA, must use API instead of HTML scraping
        if "finguider.cc" in url:
            return await self._fetch_finguider_content(url)

        # Buffett letters (PDF): use dedicated PDF extractor
        if "berkshirehathaway.com/letters/" in url:
            return await self.fetch_buffett_letter_content(url)

        # Howard Marks memos: use dedicated extractor (HTML or PDF)
        if "oaktreecapital.com" in url:
            return await self.fetch_howard_marks_content(url)

        soup = await self.news_request(url)
        if soup is None:
            return None

        result = None
        # Try specific parser first
        for key, func in self.parser_dict.items():
            if key in url:
                result = func(soup)
                break

        # Generic fallback for unrecognized or failed sources
        if not result:
            result = self._generic_news_parser(soup)

        # AI Fallback: if result is still empty or too short, use AI to extract from raw HTML
        if ai_service and (not result or len(result) < 150):
            self.logger.info(
                f"Content too short ({len(result) if result else 0}). Using AI fallback for {url}"
            )
            clean_text = self._clean_html_for_ai(soup)
            prompt = "你是一個新聞內容擷取專家。請從下方的網頁純文字內容中，擷取核心的新聞文章正文，移除廣告、選單、相關新聞推薦等雜訊。僅回傳正文內容，不要有任何額外評論。"
            try:
                # Use generate_content for simplicity
                ai_result = await ai_service.generate_content(
                    prompt + "\n\n網頁內容：\n" + clean_text[:12000]
                )
                if ai_result and len(ai_result) > (len(result) if result else 0):
                    return ai_result
            except Exception as e:
                self.logger.error(f"AI fallback extraction failed for {url}: {e}")

        return result or None

    async def fetch_cnyes_newslist(self, url: str, limit: int = 20) -> list[dict]:
        if not self.session or self.session.closed:
            await self.init_session()

        params = {"limit": limit}
        try:
            async with self.session.get(url, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
            articles = data.get("items", {}).get("data", [])
            result = []
            for article in articles:
                title = article["title"]
                content = self.clean_all(article.get("content", ""))
                pub_time = datetime.fromtimestamp(article.get("publishAt", 0)).strftime(
                    "%Y-%m-%d %H:%M"
                )
                news_url = f"https://news.cnyes.com/news/id/{article['newsId']}"
                result.append(
                    {
                        "title": title,
                        "content": content,
                        "time": pub_time,
                        "url": news_url,
                    }
                )
            return result
        except Exception as e:
            self.logger.error(f"CNYES error: {e}")
            return []

    async def fetch_news_list(self, url: str, news_number: int = 10) -> list[dict]:
        if "cnyes.com" in url:
            news_result = await self.fetch_cnyes_newslist(url, limit=news_number)
        else:
            news_result = await self.rss_parser(url)

        return news_result[:news_number]

    async def fetch_report(self, url: str, report_number: int = 10) -> list[dict]:
        if "fugle" in url:
            return await self.get_fugle_report(url)
        result = await self.rss_parser(url)
        return result[:report_number]

    async def get_fugle_report(self, url: str) -> list[dict]:
        try:
            if not self.session or self.session.closed:
                await self.init_session()

            # Categories from navbar
            category_urls = [
                "https://blog.fugle.tw/topic/industry-analysis",
                "https://blog.fugle.tw/topic/stock-analysis",
                "https://blog.fugle.tw/topic/us-stock-summary",
                "https://blog.fugle.tw/topic/earnings-call-memo",
                "https://blog.fugle.tw/topic/current-events-commentary",
                "https://blog.fugle.tw/topic/investing-for-beginners",
                "https://blog.fugle.tw/topic/stock-market-commentary",
                "https://blog.fugle.tw/topic/financial-knowledge",
                "https://blog.fugle.tw/topic/quantitative-analysis",
            ]

            async def fetch_cat(cat_url):
                try:
                    async with self.session.get(cat_url) as resp:
                        if resp.status != 200:
                            return []
                        text = await resp.text()
                    soup = BeautifulSoup(text, "html.parser")
                    links = soup.find_all("a", href=True)
                    cat_reports = []
                    for a in links:
                        href = a["href"]
                        title = a.get_text(strip=True)
                        if not title:
                            continue
                        if "/post/" in href:
                            full_link = (
                                f"https://blog.fugle.tw{href}" if href.startswith("/") else href
                            )
                            cat_reports.append({"title": title, "url": full_link})
                    return cat_reports
                except Exception as e:
                    self.logger.error(f"Fugle category error {cat_url}: {e}")
                    return []

            # Parallel fetch
            all_results = await asyncio.gather(
                *[fetch_cat(u) for u in category_urls], return_exceptions=True
            )
            reports = []
            seen_urls = set()
            for res in all_results:
                if isinstance(res, list):
                    for r in res:
                        if r["url"] not in seen_urls:
                            reports.append(r)
                            seen_urls.add(r["url"])

            return reports[:30]
        except Exception as e:
            self.logger.error(f"Fugle loop error: {e}")
            return []

    async def get_uanalyze_report(self) -> list[dict]:
        url = "https://uanalyze.com.tw/articles"
        try:
            if not self.session or self.session.closed:
                await self.init_session()
            async with self.session.get(url) as resp:
                resp.raise_for_status()
                text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            block = soup.select(".article-list")
            articles = block[0].select(".article-content") if block else []
            reports = []
            for article in articles:
                title_elem = article.select_one(".article-content__title")
                link_elem = article.select_one("a")
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    link = link_elem["href"]
                    reports.append({"title": title, "url": link})
            return reports
        except Exception as e:
            self.logger.error(f"Uanalyze error: {e}")
            return []

    async def get_moneydj_report(self) -> list[dict]:
        url = "https://www.moneydj.com/KMDJ/RssCenter.aspx?svc=NR&fno=1&arg=MB010000"
        return await self.rss_parser(url)

    async def get_vocus_articles(self, user_id: str) -> list[dict]:
        url = f"https://vocus.cc/user/{user_id}"
        try:
            if not self.session or self.session.closed:
                await self.init_session()
            async with self.session.get(url) as resp:
                resp.raise_for_status()
                text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            link_prefix = "https://vocus.cc"
            reports = []

            # Primary: __NEXT_DATA__ JSON
            import json as _json

            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                try:
                    data = _json.loads(nd.string)
                    props = data.get("props", {}).get("pageProps", {})
                    articles = props.get("articles") or props.get("articleList") or []
                    if isinstance(articles, dict):
                        articles = articles.get("items") or articles.get("data") or []
                    for art in articles:
                        if not isinstance(art, dict):
                            continue
                        title = art.get("title", "")
                        slug = art.get("slug") or art.get("_id") or art.get("id", "")
                        if title and slug:
                            url_path = f"/article/{slug}" if "/" not in slug else slug
                            reports.append({"title": title, "url": link_prefix + url_path})
                except (ValueError, KeyError):
                    pass

            # Fallback: find article links from any a[href*="/article/"]
            if not reports:
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "/article/" not in href:
                        continue
                    title = a.get_text(strip=True)
                    if not title or len(title) < 4:
                        continue
                    full_url = href if href.startswith("http") else link_prefix + href
                    if full_url not in [r["url"] for r in reports]:
                        reports.append({"title": title, "url": full_url})

            return reports
        except Exception as e:
            self.logger.error(f"Vocus error for {user_id}: {e}")
            return []

    async def get_udn_report(self) -> list[dict]:
        # UDN: Industry, Stock, International, Cross-Strait
        urls = [
            "https://money.udn.com/rssfeed/news/1001/5591",  # Industry
            "https://money.udn.com/rssfeed/news/1001/5590",  # Stock
            "https://money.udn.com/rssfeed/news/1001/5588",  # International
            "https://money.udn.com/rssfeed/news/1001/5589",  # Cross-Strait
        ]
        # Parallel fetch
        tasks = [self.rss_parser(url) for url in urls]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        for res in all_results:
            if isinstance(res, list):
                results.extend(res)
        return results

    async def get_yahoo_tw_report(self) -> list[dict]:
        url = "https://tw.stock.yahoo.com/rss?category=news"
        return await self.rss_parser(url)

    async def get_news_digest_ai_report(self) -> list[dict]:
        url = "https://feed.cqd.tw/ndai"
        return await self.rss_parser(url)

    async def get_general_rss_report(self, url: str) -> list[dict]:
        """Generic RSS fetcher for misc sources"""
        return await self.rss_parser(url)

    async def get_macromicro_report(self) -> list[dict]:
        # Fallback to morss.it proxy for blog if native RSS fails/is protected
        url = "https://morss.it/:proxy/https://www.macromicro.me/blog"
        return await self.rss_parser(url)

    async def get_finguider_report(self, limit: int = 20) -> list[dict]:
        """FinGuider: fetch latest articles via public JSON API (Vue SPA, no RSS)."""
        url = "https://finguider.cc/Api/article/"
        try:
            if not self.session or self.session.closed:
                await self.init_session()

            params = {"hot_new": "new", "page": 1}
            async with self.session.get(url, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

            items = data.get("results", [])
            results: list[dict] = []
            for it in items[: int(limit)]:
                if not isinstance(it, dict):
                    continue
                title = it.get("title", "")
                art_id = it.get("id")
                if not title:
                    continue
                link = (
                    f"https://finguider.cc/Article/ArticleIndex/{art_id}"
                    if art_id
                    else "https://finguider.cc/Article"
                )
                entry: dict = {"title": str(title), "url": link}
                # API returns full HTML content – strip tags for description
                raw_content = it.get("content", "")
                if raw_content:
                    entry["content"] = self.clean_all(raw_content)
                elif it.get("describe"):
                    entry["description"] = str(it["describe"])
                results.append(entry)
            return results
        except Exception as e:
            self.logger.error(f"FinGuider API fetch error: {e}")
            return []

    async def get_fintastic_report(self) -> list[dict]:
        url = "https://morss.it/:proxy/https://fintastic.trading/"
        return await self.rss_parser(url)

    async def get_forecastock_report(self) -> list[dict]:
        url = "https://morss.it/:proxy:items=%7C%7C*[class=articleListItem__link]/https://www.forecastock.tw/category/%E5%80%8B%E8%82%A1%E5%A0%B1%E5%91%8A"
        return await self.rss_parser(url)

    async def get_sinotrade_industry_report(self, limit: int = 20) -> list[dict]:
        endpoint = "https://www.sinotrade.com.tw/richclub/api/graphql"
        query = (
            "query {"
            f' clientGetArticleList(input:{{channel:"industry",limit:{int(limit)},page:0}}) {{'
            "   filtered { _id title pubDate image }"
            " }"
            "}"
        )
        try:
            if not self.session or self.session.closed:
                await self.init_session()

            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.sinotrade.com.tw",
                "Referer": "https://www.sinotrade.com.tw/richclub/industry",
            }
            async with self.session.post(
                endpoint, json={"query": query}, headers=headers, ssl=False
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

            items = (data or {}).get("data", {}).get("clientGetArticleList", {}).get("filtered", [])
            results: list[dict] = []
            for it in items[: int(limit)]:
                if not isinstance(it, dict):
                    continue
                title = it.get("title")
                cid = it.get("_id")
                if not title:
                    continue
                url = "https://www.sinotrade.com.tw/richclub/industry"
                if cid:
                    article_key = quote(f"x-{cid}")
                    url = f"https://www.sinotrade.com.tw/richclub/content?article={article_key}&channel=industry&type=article"
                results.append({"title": str(title), "url": url})
            return results
        except Exception as e:
            self.logger.error(f"SinoTrade industry fetch error: {e}")
            return []

    async def get_pocket_school_report(self, limit: int = 20) -> list[dict]:
        url = "https://www.pocket.tw/invest_news/api/invest_news/"
        try:
            if not self.session or self.session.closed:
                await self.init_session()

            results: list[dict] = []
            page = 1
            while len(results) < int(limit) and page <= 5:
                params = {"page": page, "category": "", "keyword": ""}
                async with self.session.get(url, params=params, ssl=False) as resp:
                    resp.raise_for_status()
                    payload = await resp.json(content_type=None)

                if not isinstance(payload, dict) or str(payload.get("code")) != "0":
                    break

                items = payload.get("data") or []
                if not isinstance(items, list) or not items:
                    break

                for it in items:
                    if not isinstance(it, dict):
                        continue
                    title = it.get("Title") or it.get("title")
                    slug = it.get("slug")
                    if not title or not slug:
                        continue
                    link = str(slug)
                    if link.startswith("/"):
                        link = f"https://www.pocket.tw{link}"
                    entry = {"title": str(title), "url": link}
                    desc = it.get("description") or it.get("meta_description")
                    if desc:
                        entry["description"] = str(desc)
                    results.append(entry)
                    if len(results) >= int(limit):
                        break

                page += 1

            return results
        except Exception as e:
            self.logger.error(f"Pocket school report fetch error: {e}")
            return []

    # ── Buffett Shareholder Letters ──────────────────────────────────────

    async def get_buffett_letters(self) -> list[dict]:
        index_url = "https://www.berkshirehathaway.com/letters/letters.html"
        try:
            if not self.session or self.session.closed:
                await self.init_session()

            async with self.session.get(index_url) as resp:
                resp.raise_for_status()
                raw = await resp.read()
                text = raw.decode("utf-8", errors="replace")

            soup = BeautifulSoup(text, "html.parser")
            results: list[dict] = []
            base = "https://www.berkshirehathaway.com/letters/"

            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                label = a.get_text(strip=True)
                if not label:
                    continue
                if href.endswith(".pdf") or (href.endswith(".html") and href != "letters.html"):
                    url = href if href.startswith("http") else base + href
                    results.append({"title": f"Buffett 股東信 — {label}", "url": url})

            results.reverse()
            return results[:5]
        except Exception as e:
            self.logger.error(f"Buffett letters fetch error: {e}")
            return []

    async def fetch_buffett_letter_content(self, url: str) -> str:
        try:
            if not self.session or self.session.closed:
                await self.init_session()

            if url.endswith(".pdf"):
                async with self.session.get(url) as resp:
                    resp.raise_for_status()
                    pdf_bytes = await resp.read()
                try:
                    import pymupdf

                    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
                    text = "\n".join(page.get_text() for page in doc)
                    doc.close()
                    return text.strip()
                except ImportError:
                    self.logger.warning("pymupdf not installed, cannot extract PDF text")
                    return ""
            else:
                soup = await self.news_request(url)
                if soup:
                    pre = soup.find("pre")
                    if pre:
                        return pre.get_text(separator="\n", strip=True)
                    body = soup.find("body")
                    if body:
                        return body.get_text(separator="\n", strip=True)
                return ""
        except Exception as e:
            self.logger.error(f"Buffett letter content error: {e}")
            return ""

    # ── Howard Marks Memos ───────────────────────────────────────────────

    async def get_howard_marks_memos(self, limit: int = 10) -> list[dict]:
        url = "https://www.oaktreecapital.com/insights/memos"
        try:
            if not self.session or self.session.closed:
                await self.init_session()

            async with self.session.get(url) as resp:
                resp.raise_for_status()
                text = await resp.text()

            soup = BeautifulSoup(text, "html.parser")
            results: list[dict] = []

            for a in soup.select("a.oc-title-link"):
                href = a.get("href", "")
                title = a.get_text(strip=True)
                if not title:
                    continue

                date_str = ""
                parent = a.find_parent()
                if parent:
                    time_el = parent.find("time", class_="embedded-date")
                    if time_el:
                        date_str = time_el.get("datetime", "") or time_el.get_text(strip=True)

                if href.startswith("/insights/memo/"):
                    full_url = f"https://www.oaktreecapital.com{href}"
                    entry = {"title": f"Howard Marks — {title}", "url": full_url}
                    if date_str:
                        entry["date"] = date_str
                    results.append(entry)
                elif "openPDF" in href:
                    import re as _re

                    m = _re.search(r"openPDF\([^,]+,\s*'([^']+)'\)", href)
                    if m:
                        pdf_url = m.group(1)
                        entry = {"title": f"Howard Marks — {title}", "url": pdf_url}
                        if date_str:
                            entry["date"] = date_str
                        results.append(entry)

                if len(results) >= int(limit):
                    break

            return results
        except Exception as e:
            self.logger.error(f"Howard Marks memos fetch error: {e}")
            return []

    def oaktree_memo_parser(self, soup) -> str:
        try:
            el = soup.select_one(".article-content")
            if el:
                for rm in el.select(
                    ".ac-left-sidebar, .ac-right-sidebar, .btn-wrap, .btnSubscribe"
                ):
                    rm.decompose()
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return text
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                return og["content"]
            return ""
        except Exception as e:
            self.logger.warning("oaktree_memo_parser failed: %s", e)
            return ""

    async def fetch_howard_marks_content(self, url: str) -> str:
        try:
            if url.endswith(".pdf") or "sfvrsn=" in url:
                if not self.session or self.session.closed:
                    await self.init_session()
                async with self.session.get(url) as resp:
                    resp.raise_for_status()
                    pdf_bytes = await resp.read()
                try:
                    import pymupdf

                    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
                    text = "\n".join(page.get_text() for page in doc)
                    doc.close()
                    return text.strip()
                except ImportError:
                    self.logger.warning("pymupdf not installed, cannot extract PDF text")
                    return ""
            else:
                soup = await self.news_request(url)
                if soup:
                    return self.oaktree_memo_parser(soup)
                return ""
        except Exception as e:
            self.logger.error(f"Howard Marks memo content error: {e}")
            return ""
