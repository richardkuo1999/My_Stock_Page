import aiohttp
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime
import html
import re
import logging
import feedparser
from dateutil import parser as dateparser
from urllib.parse import quote
from ..config import get_settings

settings = get_settings()

class NewsParser:
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Mapping sites to parser functions
        self.parser_dict = {
            'udn': self.udn_news_parser,
            'cnyes': self.cnyes_news_parser,
            'moneydj': self.moneyDJ_news_parser
        }
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        self.session = None

    async def init_session(self):
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(headers=self.headers, timeout=timeout)
        self.logger.info("NewsParser init session done")

    async def close(self):
        if self.session:
            await self.session.close()

    def clean_all(self, text):
        text = html.unescape(text)
        text = re.sub(r"<[^>]+>", "", text)
        return text

    async def rss_parser(self, url: str) -> list[dict]:
        results = []
        try:
            if not self.session:
                 await self.init_session()
                 
            async with self.session.get(url, ssl=False) as resp:
                text = await resp.text()
            feed = feedparser.parse(text)
            results = [{'title': entry.title, 
                        'url': entry.link,
                        'description': entry.description if hasattr(entry, 'description') else None,
                        'pubTime' : (dateparser.parse(entry.published) if hasattr(entry, 'published') else None),
                        'src': 'rss'} for entry in feed.entries]
        except Exception as e:
            self.logger.error(f"RSS parse error: {e}")
        return results
    
    async def news_request(self, url: str, params: dict = None) -> BeautifulSoup:
        try:
            if not self.session:
                 await self.init_session()
                 
            async with self.session.get(url, params=params, ssl=False) as resp:
                resp.raise_for_status()
                text = await resp.text()
                return BeautifulSoup(text, 'html.parser')
        except Exception as e:
            self.logger.error(f"HTTP request error: {e}")
            return None
    
    def moneyDJ_news_parser(self, soup) -> str:
        try:
            paragraphs = soup.find('article').find_all('p')
            content = "\n".join(p.get_text(strip=True) for p in paragraphs[:-1])
            return content
        except:
            return ""

    def udn_news_parser(self, soup) -> str:
        try:
            paragraphs = soup.find('section', class_="article-body__editor").find_all('p')
            content = "\n".join(p.get_text(strip=True) for p in paragraphs[:-1])
            return content
        except:
             return ""

    def cnyes_news_parser(self, soup) -> str:
        try:
            content = soup.find('main', class_='c1tt5pk2').text.strip()
            return content
        except:
            return ""

    async def fetch_news_content(self, url: str) -> str:
        soup = await self.news_request(url)
        if soup is None:
            return None
        for key, func in self.parser_dict.items():
            if key in url:
                return func(soup)
        return None

    async def fetch_cnyes_newslist(self, url: str, limit: int = 20) -> list[dict]:
        if not self.session:
             await self.init_session()

        params = {"limit": limit}
        try:
            async with self.session.get(url, params=params, ssl=False) as resp:
                resp.raise_for_status()
                data = await resp.json()
            articles = data.get("items", {}).get("data", [])
            result = []
            for article in articles:
                title = article["title"]
                content = self.clean_all(article.get("content", ""))
                pub_time = datetime.fromtimestamp(article.get("publishAt", 0)).strftime("%Y-%m-%d %H:%M")
                news_url = f"https://news.cnyes.com/news/id/{article['newsId']}"
                result.append({
                    "title": title,
                    "content": content,
                    "time": pub_time,
                    "url": news_url
                })
            return result
        except Exception as e:
            self.logger.error(f"CNYES error: {e}")
            return []

    async def fetch_news_list(self, url: str, news_number: int = 10) -> list[dict]:
        if 'cnyes.com' in url:
            news_result = await self.fetch_cnyes_newslist(url, limit=news_number)
        else:
            news_result = await self.rss_parser(url)

        return news_result[:news_number]

    async def fetch_report(self, url: str, report_number: int = 10) -> list[dict]:
        if 'fugle' in url:
            return await self.get_fugle_report(url)
        result = await self.rss_parser(url)
        return result[:report_number]

    async def get_fugle_report(self, url: str) -> list[dict]:
        try:
            if not self.session:
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
            
            reports = []
            seen_urls = set()
            
            for cat_url in category_urls:
                try:
                    async with self.session.get(cat_url, ssl=False) as resp:
                        if resp.status != 200: continue
                        text = await resp.text()
                    
                    soup = BeautifulSoup(text, "html.parser")
                    links = soup.find_all('a', href=True)
                    
                    for a in links:
                        href = a['href']
                        title = a.get_text(strip=True)
                        if not title: continue
                        
                        # Only pick actual posts, ignore topics/tags
                        if "/post/" in href:
                             full_link = f"https://blog.fugle.tw{href}" if href.startswith("/") else href
                             if full_link not in seen_urls:
                                 reports.append({'title': title, 'url': full_link})
                                 seen_urls.add(full_link)
                except Exception as e:
                    self.logger.error(f"Fugle category error {cat_url}: {e}")

            # Return a mix, maybe shuffle or just recent ones (they are likely added in order)
            return reports[:30] # Limit total
        except Exception as e:
            self.logger.error(f"Fugle loop error: {e}")
            return []

    async def get_uanalyze_report(self) -> list[dict]:
        url = 'https://uanalyze.com.tw/articles'
        try:
            if not self.session:
                 await self.init_session()
            async with self.session.get(url, ssl=False) as resp:
                resp.raise_for_status()
                text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            block = soup.select('.article-list')
            articles = block[0].select(".article-content") if block else []
            reports = []
            for article in articles:
                title_elem = article.select_one(".article-content__title")
                link_elem = article.select_one('a')
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    link = link_elem['href']
                    reports.append({'title': title, 'url': link})
            return reports
        except Exception as e:
            self.logger.error(f"Uanalyze error: {e}")
            return []
    
    async def get_moneydj_report(self) -> list[dict]:
        url = 'https://www.moneydj.com/KMDJ/RssCenter.aspx?svc=NR&fno=1&arg=MB010000'
        return await self.rss_parser(url)

    async def get_vocus_articles(self, user_id: str) -> list[dict]:
        url = f"https://vocus.cc/user/{user_id}"
        try:
            if not self.session:
                 await self.init_session()
            async with self.session.get(url, ssl=False) as resp:
                resp.raise_for_status()
                text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            link_prefix = 'https://vocus.cc'
            articles = soup.find_all("div", attrs={"class": ["dHnwX", "dDuosN"]})
            reports = []
            for article in articles:
                title_elem = article.select_one('span')
                link_elem = article.select_one('a')
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    link = link_prefix + link_elem['href']
                    reports.append({'title': title, 'url': link})
            return reports
        except Exception as e:
            self.logger.error(f"Vocus error for {user_id}: {e}")
            return []

    async def get_udn_report(self) -> list[dict]:
        # UDN: Industry, Stock, International, Cross-Strait
        urls = [
            'https://money.udn.com/rssfeed/news/1001/5591', # Industry
            'https://money.udn.com/rssfeed/news/1001/5590', # Stock
            'https://money.udn.com/rssfeed/news/1001/5588', # International
            'https://money.udn.com/rssfeed/news/1001/5589'  # Cross-Strait
        ]
        results = []
        for url in urls:
            try:
                res = await self.rss_parser(url)
                if res:
                    results.extend(res)
            except Exception as e:
                self.logger.error(f"UDN RSS error {url}: {e}")
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
        # Old config used: https://morss.it/:proxy/https://www.macromicro.me/blog
        url = "https://morss.it/:proxy/https://www.macromicro.me/blog"
        return await self.rss_parser(url)

    async def get_finguider_report(self) -> list[dict]:
        # Use Morss.it proxy for FinGuider Article list
        url = "https://morss.it/:proxy/https://finguider.cc/Article"
        return await self.rss_parser(url)

    async def get_fintastic_report(self) -> list[dict]:
        # Old config: https://morss.it/:proxy/https://fintastic.trading/
        url = "https://morss.it/:proxy/https://fintastic.trading/"
        return await self.rss_parser(url)

    async def get_forecastock_report(self) -> list[dict]:
        # Old config: https://morss.it/:proxy:items=%7C%7C*[class=articleListItem__link]/https://www.forecastock.tw/category/%E5%80%8B%E8%82%A1%E5%A0%B1%E5%91%8A
        # This includes custom selector for morss.it
        url = "https://morss.it/:proxy:items=%7C%7C*[class=articleListItem__link]/https://www.forecastock.tw/category/%E5%80%8B%E8%82%A1%E5%A0%B1%E5%91%8A"
        return await self.rss_parser(url)

    async def get_sinotrade_industry_report(self, limit: int = 20) -> list[dict]:
        """
        SinoTrade RichClub: 3分鐘產業百科（GraphQL）。

        Note: GraphQL 的 ContentPayload `link` 欄位會觸發 500，`url` 也常為 null。
        但前端內頁實際是走 `content?article=<prefix>-<id>&channel=industry&type=article`，
        其中 `<prefix>` 可任意，只要 `-<id>` 結尾即可解析出文章。
        """
        endpoint = "https://www.sinotrade.com.tw/richclub/api/graphql"
        query = (
            'query {'
            f' clientGetArticleList(input:{{channel:"industry",limit:{int(limit)},page:0}}) {{'
            '   filtered { _id title pubDate image }'
            ' }'
            '}'
        )
        try:
            if not self.session:
                await self.init_session()

            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://www.sinotrade.com.tw",
                "Referer": "https://www.sinotrade.com.tw/richclub/industry",
            }
            async with self.session.post(endpoint, json={"query": query}, headers=headers, ssl=False) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

            items = (
                (data or {})
                .get("data", {})
                .get("clientGetArticleList", {})
                .get("filtered", [])
            )
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
        """
        Pocket 學堂：研究報告（最新列表）。

        使用 `invest_news/api/invest_news`，回傳內含 `Title` 與 `slug`（即內頁路徑）。
        """
        url = "https://www.pocket.tw/invest_news/api/invest_news/"
        try:
            if not self.session:
                await self.init_session()

            results: list[dict] = []
            page = 1
            # Best-effort pagination; stop once we have enough or page looks empty.
            while len(results) < int(limit) and page <= 5:
                params = {"page": page, "category": "", "keyword": ""}
                async with self.session.get(url, params=params, ssl=False) as resp:
                    resp.raise_for_status()
                    payload = await resp.json(content_type=None)

                # Pocket API sometimes returns code as int(0) or str("0")
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
                    # slug looks like: /school/report/perspective/7002/
                    link = str(slug)
                    if link.startswith("/"):
                        link = f"https://www.pocket.tw{link}"
                    results.append({"title": str(title), "url": link})
                    if len(results) >= int(limit):
                        break

                page += 1

            return results
        except Exception as e:
            self.logger.error(f"Pocket school report fetch error: {e}")
            return []
