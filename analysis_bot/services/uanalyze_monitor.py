"""UAnalyze 報告監控服務：定時抓取新報告並推播 Telegram。"""

import html
import json
import logging
from datetime import datetime
from pathlib import Path

import aiohttp

from ..config import get_settings
from .http import create_session

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/uanalyze/last_seen_id.json")


def _load_last_id() -> int:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_id", 0)
        except Exception:
            pass
    return 0


def _save_last_id(last_id: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"last_id": last_id, "updated_at": datetime.now().isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


def _format_report(report: dict, index: int, total: int, keywords: list[str]) -> tuple[str, bool]:
    """Format a single report. Returns (html_text, has_keyword)."""
    name = report.get("name", "")
    stock_name = report.get("stock_name", "")
    date = report.get("content_date", "")[:10]
    summary = report.get("summary", "")

    has_kw = any(k and (k in name or k in stock_name or k in summary) for k in keywords)

    name_esc = html.escape(name)
    stock_esc = html.escape(stock_name)
    summary_esc = html.escape(summary)

    for kw in keywords:
        if not kw:
            continue
        kw_esc = html.escape(kw)
        bold = f"<b>{kw_esc}</b>"
        name_esc = name_esc.replace(kw_esc, bold)
        stock_esc = stock_esc.replace(kw_esc, bold)
        summary_esc = summary_esc.replace(kw_esc, bold)

    text = (
        f"📋 [{index}/{total}] [{name_esc}] {stock_esc}\n"
        f"📅 {html.escape(date)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{summary_esc}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    return text, has_kw


async def check_new_reports(bot=None, dry_run: bool = False) -> int:
    """Check for new reports and send to Telegram. Returns count of new reports."""
    settings = get_settings()
    api_url = settings.UANALYZE_API_URL
    if not api_url:
        return 0

    keywords = [k.strip() for k in settings.UANALYZE_KEYWORDS.split(",") if k.strip()]
    chat_id = settings.TELEGRAM_AI_NEWS_CHAT_ID
    topic_id = settings.TELEGRAM_AI_NEWS_TOPIC_ID or None

    async with create_session() as session:
        # Fetch reports
        try:
            async with session.get(api_url, params={"limit": 50, "offset": 0}, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("UAnalyze API status: %s", resp.status)
                    return 0
                data = await resp.json()
                reports = data.get("data", {}).get("data", [])
        except Exception as e:
            logger.error("UAnalyze API error: %s", e)
            return 0

    if not reports:
        return 0

    last_id = _load_last_id()
    new_reports = sorted([r for r in reports if r.get("id", 0) > last_id], key=lambda r: r["id"])

    # First run: just save state
    if last_id == 0:
        _save_last_id(max(r.get("id", 0) for r in reports))
        logger.info("UAnalyze monitor: initialized last_id=%d", max(r.get("id", 0) for r in reports))
        return 0

    if not new_reports:
        return 0

    logger.info("UAnalyze: %d new reports", len(new_reports))

    if not dry_run and bot and chat_id:
        total = len(new_reports)
        for i, report in enumerate(new_reports, 1):
            text, has_kw = _format_report(report, i, total, keywords)
            kwargs = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_notification": not has_kw}
            if topic_id:
                kwargs["message_thread_id"] = topic_id
            try:
                await bot.send_message(**kwargs)
            except Exception as e:
                logger.error("UAnalyze telegram send error: %s", e)
            if i < total:
                import asyncio
                await asyncio.sleep(0.3)

    _save_last_id(max(r["id"] for r in new_reports))
    return len(new_reports)
