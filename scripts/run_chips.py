#!/usr/bin/env python3
"""
Standalone 執行 Blake CHIPS 抓取。

用法：
   python scripts/run_chips.py              # 00981A 今天
   python scripts/run_chips.py 2026-03-18   # 00981A 指定日期
   python scripts/run_chips.py 888          # 00981A_match_888 今天
   python scripts/run_chips.py 888 2026-03-18  # 00981A_match_888 指定日期
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis_bot.services.blake_chips_scraper import fetch_chips_data, fetch_chips_data_888


def main():
    args = sys.argv[1:]
    try:
        if args and args[0] == "888":
            date_str = args[1] if len(args) > 1 else None
            text = asyncio.run(fetch_chips_data_888(date_str=date_str))
        else:
            date_str = args[0] if args else None
            text = asyncio.run(fetch_chips_data(date_str=date_str))
        print(text)
    except Exception as e:
        print(f"❌ 錯誤：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
