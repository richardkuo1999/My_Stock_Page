"""UAnalyze 報告監控服務：定時抓取新報告並推播 Telegram。"""

import html
import logging
from datetime import datetime

import aiohttp

from ..config import get_settings
from .http import create_session

logger = logging.getLogger(__name__)

_LAST_ID_KEY = "umon_last_seen_id"


def _load_last_id() -> int:
    from sqlmodel import Session as _S, select as _sel
    import analysis_bot.database as _db
    from ..models.config import SystemConfig
    try:
        with _S(_db.engine) as s:
            row = s.exec(_sel(SystemConfig).where(SystemConfig.key == _LAST_ID_KEY)).first()
            if row:
                return int(row.value)
    except Exception:
        pass
    return 0


def _save_last_id(last_id: int) -> None:
    from sqlmodel import Session as _S, select as _sel
    import analysis_bot.database as _db
    from ..models.config import SystemConfig
    with _S(_db.engine) as s:
        row = s.exec(_sel(SystemConfig).where(SystemConfig.key == _LAST_ID_KEY)).first()
        if row:
            row.value = str(last_id)
            row.updated_at = datetime.now()
        else:
            row = SystemConfig(key=_LAST_ID_KEY, value=str(last_id), description="UAnalyze monitor last seen report id")
        s.add(row)
        s.commit()


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

    # Load all push targets from DB
    from sqlmodel import Session as _Session, select as _select
    from ..models.umon_target import UmonTarget
    import analysis_bot.database as _db
    with _Session(_db.engine) as _s:
        targets = _s.exec(_select(UmonTarget)).all()

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

    if not dry_run and bot and targets:
        total = len(new_reports)
        for i, report in enumerate(new_reports, 1):
            text, has_kw = _format_report(report, i, total, keywords)
            for t in targets:
                kwargs = {"chat_id": t.chat_id, "text": text, "parse_mode": "HTML", "disable_notification": not has_kw}
                if t.topic_id:
                    kwargs["message_thread_id"] = t.topic_id
                try:
                    await bot.send_message(**kwargs)
                except Exception as e:
                    logger.error("UAnalyze send error (chat=%s): %s", t.chat_id, e)
            if i < total:
                import asyncio
                await asyncio.sleep(0.3)

    _save_last_id(max(r["id"] for r in new_reports))
    return len(new_reports)
