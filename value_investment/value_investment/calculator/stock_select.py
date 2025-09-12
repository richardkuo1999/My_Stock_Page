import re
import os
import sys
import aiohttp
import asyncio
import pandas as pd
from natsort import natsorted
from collections import Counter

sys.path.append(os.path.dirname(__file__) + "/..")

from utils.utils import logger, fetch_webpage, is_ordinary_stock

FILTER = '1Y_Return'
TARGET_ROI = 10 # %
NUM_ETF_GET = 10

ETF_BASE_URL = "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={}"
ETF_RANK_URL = "https://www.moneydj.com/ETF/X/Rank/Rank0007.xdjhtm?eRank=irr&eOrd=t800652&eMid=TW&eArea=0&eTarget=22&eCoin=AX000010&eTab=1"
INVESTOR_URL = "https://histock.tw/stock/three.aspx?s={}"
INVESTOR_TYPES = {"foreign": "a", "investment_trust": "b", "dealers": "c"}

async def parse_etf_rank_data(session):
    # Parse HTML content with BeautifulSoup
    soup = await fetch_webpage(session, ETF_RANK_URL)
    
    # Find the table containing ETF data
    table = soup.find('table', myid='oMainTable')

    # Extract headers
    headers = []
    header_row = table.find('thead').find_all('tr')[0]  # Second row contains actual headers
    for th in header_row.find_all('th'):
        headers.append(th.text.strip())
    
    # Extract data rows
    rows = []
    for tr in table.find('tbody').find_all('tr'):
        row = []
        for td in tr.find_all('td'):
            # Extract text, handling links and checkboxes
            text = td.text.strip()
            if td.find('a'):
                if td.find('a').get('etfid'):
                    text = td.find('a')['etfid']
                else:
                    text = td.find('a').text.strip()
            row.append(text)
        rows.append(row)
    
    # Create DataFrame
    df = pd.DataFrame(rows, columns=headers)
    
    # Clean and adjust columns
    # Remove the first two columns (checkbox and image)
    df = df.drop(columns=[df.columns[0], df.columns[1]])
    
    # Rename columns for clarity
    df.columns = [
        'Rank', 'ETF_Code', 'ETF_Name', 'Date', 'Currency',
        'Annualized_Return_Since_Inception', '1D_Return', '1W_Return',
        'YTD_Return', '1M_Return', '3M_Return', '1Y_Return'
    ]
    
    # Convert numeric columns to float
    numeric_columns = [
        'Annualized_Return_Since_Inception', '1D_Return', '1W_Return',
        'YTD_Return', '1M_Return', '3M_Return', '1Y_Return'
    ]
    for col in numeric_columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Convert Rank to integer
    df['Rank'] = pd.to_numeric(df['Rank'], errors='coerce', downcast='integer')
    
    return df

async def fetch_etf_constituents(session, etf_id: str) -> list[str]:
    try:
        soup = await fetch_webpage(session, ETF_BASE_URL.format(etf_id))
        constituents = {
            match.group(1)
            for a in soup.select("td.col05 a")
            if (href := a.get("href")) and (match := re.search(r"etfid=(\d+)\.", href))
        }
        return natsorted(constituents)
    except (ValueError, AttributeError, asyncio.TimeoutError) as e:
        logger.error(f"[Error] Failed to fetch ETF constituents for {etf_id}: {str(e)}")
        return []

async def fetch_investor_stocks(session, investor_type: str) -> list[str]:
    try:
        soup = await fetch_webpage(session, INVESTOR_URL.format(investor_type))
        stocks = [
            element.text.strip()
            for element in soup.find_all("span", class_="w58")[::6]
            if is_ordinary_stock(element.text.strip())
        ]
        return stocks
    except (ValueError, AttributeError, asyncio.TimeoutError) as e:
        logger.error(
            f"Failed to fetch stocks for investor type {investor_type}: {str(e)}"
        )
        return []

async def fetch_institutional_top50(session) -> list[str]:
    tasks = [
        fetch_investor_stocks(session ,investor_type)
        for investor_type in INVESTOR_TYPES.values()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_stocks = set()

    for result in results:
        if isinstance(result, list):
            all_stocks.update(result)

    return natsorted(all_stocks)

async def fetch_etf_rank_stocks(session):
    stocks = []
    df = await parse_etf_rank_data(session)
    df_filtered = df[df[FILTER] > TARGET_ROI]

    tasks = []
    for _, row in df_filtered.iterrows():
        etf_id = row['ETF_Code']
        tasks.append(fetch_etf_constituents(session, etf_id))

    results = await asyncio.gather(*tasks)
    # Flatten all constituents into a single list
    all_constituents = [c for sublist in results for c in sublist]
    counts = Counter(all_constituents)

    for (idx, (_, row)) in enumerate(df_filtered.iterrows()):
        constituents = results[idx]
        logger.debug(f"ETF: {row['ETF_Name']} ({row['ETF_Code']})")
        logger.debug(f"Constituents: {constituents}")
        logger.debug("-" * 40)

    logger.debug("Constituent occurrence counts:")
    for constituent, count in counts.most_common():
        if count >= NUM_ETF_GET:
            stocks.append(constituent)
        logger.debug(f"{constituent}: {count}")
    return natsorted(stocks)

async def main():
    # Fetch ETF constituents
    etf_id = "0050.TW"

    # Fetch stocks for each investor type concurrently
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_etf_constituents(session, etf_id),
            fetch_investor_stocks(session, INVESTOR_TYPES["foreign"]),
            fetch_institutional_top50(session),
            fetch_etf_rank_stocks(session)
        ]
        etf_stocks, investor_stocks, top_50, etf_rank = await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(f"ETF {etf_id} constituents: {etf_stocks}")

    logger.info(f"foreign stocks (count: {len(investor_stocks)}): {investor_stocks}")

    logger.info(f"Top 50 institutional stocks (count: {len(top_50)}): {top_50}")
    logger.info(f"ETF Rank Stock (count: {len(etf_rank)}): {etf_rank}")


if __name__ == "__main__":
    asyncio.run(main())
