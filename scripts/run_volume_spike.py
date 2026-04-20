#!/usr/bin/env python3
"""
手動執行爆量偵測（不透過排程）

使用方式:
    python scripts/run_volume_spike.py              # 預設按倍數排序
    python scripts/run_volume_spike.py change       # 按漲幅排序
    python scripts/run_volume_spike.py --send       # 推送到 Telegram
    python scripts/run_volume_spike.py --send change  # 按漲幅排序並推送
    python scripts/run_volume_spike.py --send --news  # 含新聞分析
"""
import asyncio
import sys
from pathlib import Path

# 確保專案根目錄在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main():
    from analysis_bot.services.volume_spike_scanner import VolumeSpikeScanner, SpikeSortBy
    from analysis_bot.config import get_settings

    send_to_telegram = "--send" in sys.argv or "-s" in sys.argv
    with_news = "--news" in sys.argv or "-n" in sys.argv

    # 解析排序參數（非 -- 開頭的參數）
    sort_arg = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-") and arg in ("ratio", "change"):
            sort_arg = arg
            break

    sort_by = SpikeSortBy(sort_arg) if sort_arg else SpikeSortBy.RATIO

    scanner = VolumeSpikeScanner()
    spike_scan = await scanner.scan(sort_by=sort_by)
    results = spike_scan.results

    if not results:
        print("📊 今日無爆量股（成交量 ≥ 1000 張，倍數 ≥ 1.5x）")
        return

    from analysis_bot.services.volume_spike_formatter import (
        NAME_W,
        PRICE_CHG_W,
        RATIO_FIELD_W,
        TICKER_W,
        display_width,
        pad_price_chg_cell,
        pad_stock_name,
        pad_visual,
    )

    # 終端可略寬於 Telegram；成交量以千位逗號對齊顯示寬度
    PRICE_CHG_CONSOLE_W = max(PRICE_CHG_W, 20)
    VOL_W = 14

    def _pad_vol_str(vol_lots: int) -> str:
        s = f"{vol_lots:,}"
        w = display_width(s)
        if w >= VOL_W:
            return s
        return " " * (VOL_W - w) + s

    dash_len = (
        TICKER_W
        + NAME_W
        + PRICE_CHG_CONSOLE_W
        + 2
        + VOL_W
        + 1
        + RATIO_FIELD_W
    )

    print(f"\n🔥 爆量偵測 ({len(results)} 檔) ｜ {spike_scan.data_date_caption}\n")
    hdr = (
        f"{pad_visual('代碼', TICKER_W)}"
        f"{pad_visual('名稱', NAME_W)}"
        f"{pad_visual('股價(漲幅)', PRICE_CHG_CONSOLE_W)}"
        f"  {pad_visual('成交量(張)', VOL_W)}"
        f" {pad_visual('倍數', RATIO_FIELD_W)}"
    )
    print(hdr)
    print("-" * dash_len)
    for r in results:
        vol_lots = r.today_volume // 1000
        ratio_s = f"{r.spike_ratio:>6.1f}x".rjust(RATIO_FIELD_W)
        row = (
            f"{pad_visual(str(r.ticker), TICKER_W)}"
            f"{pad_stock_name(r.name)}"
            f"{pad_price_chg_cell(r, PRICE_CHG_CONSOLE_W)}"
            f"  {_pad_vol_str(vol_lots)}"
            f" {ratio_s}"
        )
        print(row)

    if send_to_telegram:
        settings = get_settings()
        if not settings.TELEGRAM_TOKEN or not settings.TELEGRAM_CHAT_ID:
            print("\n⚠️ 未設定 TELEGRAM_TOKEN / TELEGRAM_CHAT_ID，無法推送")
            return

        from analysis_bot.services.spike_pager import (
            build_spike_markdown_header,
            build_spike_telegram_html_messages,
        )
        from telegram import Bot

        bot = Bot(token=settings.TELEGRAM_TOKEN)
        chat_id = settings.TELEGRAM_CHAT_ID

        hdr = build_spike_markdown_header(len(results), sort_by=sort_by)
        spike_msgs = build_spike_telegram_html_messages(results, hdr)
        for i, m in enumerate(spike_msgs):
            if i > 0:
                await asyncio.sleep(0.5)
            await bot.send_message(
                chat_id=chat_id,
                text=m,
                parse_mode="HTML",
            )

        if with_news and settings.SPIKE_NEWS_ENRICHMENT_ENABLED:
            await bot.send_message(chat_id=chat_id, text="📰 正在擷取爆量第 1 檔題材（試跑）…")
            results = await scanner.enrich_with_news(results, top_n=1, max_news_per_stock=5)
            r = results[0]
            if r.analysis and r.analysis != "近期無相關新聞":
                detail = f"📈 *{r.name}*（{r.ticker}）{r.spike_ratio:.1f}x\n{r.analysis}"
                if r.news_titles:
                    detail += "\n\n_相關新聞：_ " + "；".join(r.news_titles[:3])
                await bot.send_message(chat_id=chat_id, text=detail, parse_mode="Markdown")

        print("\n✓ 已推送到 Telegram")


if __name__ == "__main__":
    asyncio.run(main())
