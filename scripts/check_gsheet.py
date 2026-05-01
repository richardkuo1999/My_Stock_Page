#!/usr/bin/env python3
"""
快速測試 Google Sheets 抓取結果。

用法：
    python scripts/check_gsheet.py
    python scripts/check_gsheet.py "https://docs.google.com/spreadsheets/d/xxx/edit?gid=0#gid=0"

不帶參數時，讀取 .env 中的 GSHEET_MONITOR_URLS。
"""

import asyncio
import sys
from pathlib import Path

# 讓 import 能找到 analysis_bot
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()


async def main():
    from analysis_bot.services.gsheet_monitor import (
        _parse_sheet_url,
        fetch_sheet_csv,
        _extract_preview,
        _hash_content,
        _load_hash,
    )

    # 決定要抓哪些 URL
    if len(sys.argv) > 1:
        urls = sys.argv[1:]
    else:
        from analysis_bot.config import get_settings

        settings = get_settings()
        urls = settings.GSHEET_MONITOR_URLS
        if not urls:
            print("❌ 沒有設定 GSHEET_MONITOR_URLS，請在 .env 中設定或直接傳入 URL 參數")
            sys.exit(1)

    for url in urls:
        print(f"\n{'='*60}")
        print(f"📊 URL: {url}")
        print(f"{'='*60}")

        try:
            sheet_id, gid = _parse_sheet_url(url)
            print(f"   Sheet ID: {sheet_id}")
            print(f"   GID: {gid}")
        except ValueError as e:
            print(f"   ❌ 無法解析 URL: {e}")
            continue

        csv_text = await fetch_sheet_csv(sheet_id, gid)
        if csv_text is None:
            print("   ❌ 抓取失敗（試算表可能不是公開的）")
            continue

        current_hash = _hash_content(csv_text)
        previous_hash = _load_hash(sheet_id, gid)

        print(f"   目前 hash: {current_hash[:16]}...")
        if previous_hash:
            print(f"   上次 hash: {previous_hash[:16]}...")
            if current_hash == previous_hash:
                print("   ✅ 無變更")
            else:
                print("   🔔 有變更！")
        else:
            print("   ℹ️  首次抓取（尚無歷史紀錄）")

        # 顯示預覽
        rows = _extract_preview(csv_text)
        print(f"\n   📋 前 {len(rows)} 行預覽：")
        print(f"   {'─'*50}")
        for i, row in enumerate(rows):
            cells = [c[:25] for c in row[:6]]
            line = " | ".join(cells)
            print(f"   {i+1:2d}. {line}")


if __name__ == "__main__":
    asyncio.run(main())
