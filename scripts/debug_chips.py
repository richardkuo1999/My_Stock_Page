#!/usr/bin/env python3
"""
Debug CHIPS 抓取：比對「原始全部」與「篩選後」的差異。
用法：python scripts/debug_chips.py [date]
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp
from bs4 import BeautifulSoup

BASE_URL = "https://blake-finance-notes.org/chips_blake_finance/code_php/00981A.php"


async def fetch_raw(date_str: str) -> str:
    url = f"{BASE_URL}?date={date_str}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            return await r.text()


def parse_all(html: str) -> list[str]:
    """解析全部表格，不篩選。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    lines = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if cells:
                row_text = " | ".join(c.get_text(strip=True) for c in cells)
                if row_text:
                    lines.append(row_text)
    return lines


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else "2026-03-18"
    html = asyncio.run(fetch_raw(date_str))

    all_rows = parse_all(html)
    print(f"=== 原始全部 ({len(all_rows)} 行) ===")
    for i, row in enumerate(all_rows[:80]):
        print(f"{i+1:3}: {row[:120]}{'...' if len(row) > 120 else ''}")
    if len(all_rows) > 80:
        print(f"... 還有 {len(all_rows) - 80} 行")

    print("\n=== 透過 fetch_chips_data 篩選（張數有變化）===")
    from analysis_bot.services.blake_chips_scraper import fetch_chips_data

    result = asyncio.run(fetch_chips_data(date_str=date_str))
    print(result)


if __name__ == "__main__":
    main()
