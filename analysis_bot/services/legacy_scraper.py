import aiohttp
import asyncio
import logging
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
import re

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.99 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

GOODINFO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.99 Safari/537.36",
    "Cookie": "CLIENT%5FID=20241210210956023%5F111%2E255%2E220%2E131; IS_TOUCH_DEVICE=F; SCREEN_SIZE=WIDTH=1710&HEIGHT=1112; TW_STOCK_BROWSE_LIST=2330; _ga=GA1.1.812880287.1733836199; _cc_id=28e3f970dec12837e20c15307c56ec28; panoramaId_expiry=1734441000958; panoramaId=cc21caa7184af9f0e6c620d0a8f8185ca02cc713f5ac9a4263f82337f1b4a2b7; panoramaIdType=panoDevice; __gads=ID=b2e3ed3af73d1ae3:T=1733836201:RT=1733922308:S=ALNI_Mb7ThRkzKYSy21PA-6lcXT9vRc3Kg; __gpi=UID=00000f896331f355:T=1733836201:RT=1733922308:S=ALNI_MZqCnVGqHlRq9KdKeQAuDHF4Gjfxw; __eoi=ID=f9846d25b9e203d1:T=1733836201:RT=1733922308:S=AA-AfjY-BVqunx2hOWeWbgCq5_UI; cto_bundle=Lk53dF84ZDdteU1aenVEZW9WZklPTG5FYU9MdDRjOFQ5NkVoZ1lYOTVnMzNVTFFDOUFNYXZyWjBmSndHemVhOFdhQTlMZHJUNCUyQiUyRm9RSlJpd0FBUXlYd2NDQmdXRkh0ZkM1SUY1VHM2b2NQc0ljcVJGSTFwY3RPRmI1WEwxRXBMTVUzUDgxWjBLSUVjOSUyQk1veUdMcFZjRDlsNVElM0QlM0Q; cto_bundle=4XBCG184ZDdteU1aenVEZW9WZklPTG5FYU9NcXlSZm1lU2RKOGgwaHlUM1RzWXU5QWMlMkJuR1lkb25qSjdRYUxHWWhsUEhMRGxCeHVuUVF6WGlGTkxjbVNuYmFqbERVRm11QjlTR0xBckVvdmE2ZlJFQmhQdURma3lnRHNjM25xOFpNNEg4WWZLc0wxZVN6c1lEUFZDM3VvNnlxdWFGV2FiNThNRSUyRlZ4N3ZxakZzT3I0cEclMkZYdm1NN2RQNSUyRlBUM1FQJTJCSE80YUxVVDlKUUFLblZuMllUZVBzaVdFZyUzRCUzRA; cto_bidid=NK15uF9ZWnQ2aGIwVGNqRUFJRGgxVUVSejh0b1dEczFNU0FJTmR1RVl5SnljdDVmY08xc1NndnRUZXZMYmVvJTJCMVNya2R5RVk1QWpEeiUyQnBsJTJCOUZJQTBWJTJGcGhTcWFvUGs1QkxuUCUyQnVjUU42MXZIQWxSb2xsVVFrNml2T2g0TG1NcHphS0I4YzdzQXVRVXpRSXlCZU1VV1M4SDN3JTNEJTNE; FCNEC=%5B%5B%22AKsRol-AsNGK3J633zneXVvjb6XxOsqQYrBvxCwcMi0GME-2BDMLBX3LEYQ83Li8Hw71LSdsgNxpfHUX3Nw3FGDMDQhm3wUeXgalEarK4zql1IO51tBobJmU-o44Bd5tOC0OcT6RNUf2w8Bl6YsQ6f2yA7JoK-Uwlw%3D%3D%22%5D%5D; _ga_0LP5MLQS7E=GS1.1.1733921765.2.1.1733922576.51.0.0",
    "Referer": "https://goodinfo.tw/tw/BasicInfo.asp",
}

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type((aiohttp.ClientError, Exception)),
)
async def fetch_webpage(session, url: str, headers: dict = DEFAULT_HEADERS, timeout: int = 10) -> BeautifulSoup | None:
    try:
        is_moneydj = "moneydj.com" in url
        async with session.get(
            url,
            headers=headers,
            timeout=timeout,
            ssl=(not is_moneydj),
        ) as response:
            response.raise_for_status()
            text = await response.text(encoding="utf-8")
            return BeautifulSoup(text, "html.parser") # html5lib might not be installed, using html.parser
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        raise

class Goodinfo:
    COMPANY_INFO_BASE_URL = "https://goodinfo.tw/tw/BasicInfo.asp?STOCK_ID={}"

    async def fetch_data(self, session, stock_id: str):
        # We only need company info for MoneyDJ url construction in the legacy logic
        company_info = await self.get_company_info(session, stock_id)
        return {"company_info": company_info}

    async def get_company_info(self, session, stock_id):
        url = self.COMPANY_INFO_BASE_URL.format(stock_id)
        try:
            logger.info(f"Fetching Goodinfo URL: {url}")
            soup = await fetch_webpage(session, url, GOODINFO_HEADERS)
            if not soup:
                 logger.error(f"Failed to fetch soup for {url}")
                 return None
                 
            info_dict = {}
            
            raw_keys = soup.find_all("th", {"class": "bg_h1"})
            raw_values = soup.find_all("td", {"bgcolor": "white"})
            
            logger.info(f"Found {len(raw_keys)} keys and {len(raw_values)} values for {stock_id}")
            
            for k, v in zip(raw_keys, raw_values):
                key = k.get_text(strip=True)
                val = v.get_text(strip=True)
                info_dict[key] = val
            
            logger.info(f"Parsed info keys: {list(info_dict.keys())}")
            return info_dict
        except Exception as e:
            logger.error(f"Goodinfo fetch error {stock_id}: {e}")
            return None

class LegacyMoneyDJ:
    def __init__(self) -> None:
        self.query_url = "https://www.moneydj.com/kmdj/search/list.aspx?_Query_="
        self.wiki_url = "&_QueryType_=WK"
        self.prefix_url = "https://www.moneydj.com/kmdj/"

    async def get_company_url(self, session, stock_id) -> str | None:
        goodinfo = Goodinfo()
        goodinfo_data = await goodinfo.fetch_data(session, stock_id)
        if not goodinfo_data or not goodinfo_data.get("company_info"):
            logger.warning(f"No Goodinfo data for {stock_id}")
            return None, None

        c_info = goodinfo_data["company_info"]
        company_name = c_info.get('公司名稱')
        stock_name = c_info.get('股票名稱')
        
        if not company_name:
            return None, None

        # Clean name
        company_name_clean = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", company_name)
        
        # Search MoneyDJ
        url = self.query_url + company_name_clean + self.wiki_url
        soup = await fetch_webpage(session, url, headers=GOODINFO_HEADERS)
        if not soup:
            return stock_name, None

        # Logic: find td with string=company_name
        # section_title = soup.find("td", string=company_name)
        # BS4 string argument matches exact string.
        section_title = soup.find("td", string=company_name)
        
        company_url = None
        if section_title:
             link = section_title.select_one('a')
             if link:
                 href = link.get("href")
                 # href usually starts with ../wiki/.... , prefix is https://www.moneydj.com/kmdj/
                 # if href is relative like ../, we need to handle it.
                 # Old code: company_url = self.prefix_url + company_url[2:] 
                 # implicating href is `../wiki/...`
                 if href.startswith(".."):
                     company_url = self.prefix_url + href[3:] # skip ../
                 else:
                     company_url = self.prefix_url + href
        else:
            logger.warning(f"MoneyDJ search failed for {company_name}")

        return stock_name, company_url

    async def get_wiki_result(self, stock_id) -> tuple[str, str] | tuple[None, None]:
        async with aiohttp.ClientSession() as session:
            stock_name, company_url = await self.get_company_url(session, stock_id)
            if not company_url:
                return None, None
            
            soup = await fetch_webpage(session, company_url, headers=GOODINFO_HEADERS)
            if not soup:
                return stock_name, None

            # data = soup.find('div', class_='UserDefined') # Old commented out
            data = soup.find('article')
            
            if data:
                raw_text = data.get_text(separator='\n', strip=True)
                lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
                clean_text = '\n'.join(lines)
                return stock_name, clean_text
            
            return stock_name, ""
