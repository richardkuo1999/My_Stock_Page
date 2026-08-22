"""APScheduler jobs for news push notifications."""

import json
import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

PUSHED_NEWS_PATH = Path("data/pushed_news.json")
NEWS_TTL_DAYS = 7
SIMILARITY_THRESHOLD = 0.8  # titles with >80% similarity are considered duplicates

PUSHED_THREADS_PATH = Path("data/pushed_threads.json")
THREADS_TTL_DAYS = 3

PUSHED_UANALYZE_PATH = Path("data/pushed_uanalyze.json")
UANALYZE_TTL_DAYS = 14


def _load_pushed_news() -> list[dict]:
    """Load pushed news records from JSON file."""
    if not PUSHED_NEWS_PATH.exists():
        return []
    try:
        return json.loads(PUSHED_NEWS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_pushed_news(records: list[dict]) -> None:
    """Save pushed news records to JSON file."""
    PUSHED_NEWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUSHED_NEWS_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _cleanup_expired(records: list[dict]) -> list[dict]:
    """Remove records older than NEWS_TTL_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_TTL_DAYS)
    result = []
    for r in records:
        try:
            pushed_at = datetime.fromisoformat(r["pushed_at"])
            if pushed_at.tzinfo is None:
                pushed_at = pushed_at.replace(tzinfo=timezone.utc)
            if pushed_at > cutoff:
                result.append(r)
        except (KeyError, ValueError):
            continue
    return result


def _is_duplicate_title(title: str, existing_titles: list[str]) -> bool:
    """Check if title is similar to any existing title (fuzzy dedup)."""
    if not title:
        return False
    for existing in existing_titles:
        if not existing:
            continue
        ratio = SequenceMatcher(None, title, existing).ratio()
        if ratio >= SIMILARITY_THRESHOLD:
            return True
    return False


async def news_push_job(bot, subscription_manager, agent_bridge) -> None:
    """Scheduled job: fetch news, filter duplicates, summarize, push to subscribers."""
    from tools.fetch_news import latest

    logger.info("News push job started")

    # Fetch articles
    try:
        result = await latest()
        articles = result.get("articles", []) if isinstance(result, dict) else result
    except Exception as e:
        logger.error("Failed to fetch news: %s", e)
        return

    if not articles:
        logger.info("No new articles found")
        return

    # Load and cleanup pushed records
    pushed_records = _load_pushed_news()
    pushed_records = _cleanup_expired(pushed_records)
    pushed_urls = {r["url"] for r in pushed_records}
    pushed_titles = [r.get("title", "") for r in pushed_records]

    # Filter new articles (URL dedup + fuzzy title dedup)
    new_articles = []
    for article in articles:
        url = article.get("url", "")
        title = article.get("title", "")
        if not url:
            continue
        if url in pushed_urls:
            continue
        if _is_duplicate_title(title, pushed_titles):
            continue
        new_articles.append(article)
        pushed_titles.append(title)  # prevent duplicates within same batch

    if not new_articles:
        logger.info("All articles already pushed")
        _save_pushed_news(pushed_records)
        return

    # Get subscribers
    subscribers = subscription_manager.get_subscribers("news")
    if not subscribers:
        logger.info("No news subscribers")
        # Still record as pushed to avoid re-processing next run
        now = datetime.now(timezone.utc).isoformat()
        for article in new_articles:
            pushed_records.append({
                "url": article["url"],
                "title": article.get("title", ""),
                "pushed_at": now,
            })
        _save_pushed_news(pushed_records)
        return

    # Summarize via AgentBridge (batch, max 10 articles)
    summary = None
    batch = new_articles[:10]
    if agent_bridge:
        try:
            news_json = json.dumps(
                [{"title": a.get("title", ""), "source": a.get("source", ""), "url": a["url"]} for a in batch],
                ensure_ascii=False,
            )
            prompt = (
                "請用繁體中文摘要以下新聞，每則一行，"
                "格式「• [來源] 標題摘要\\n  └ URL」：\n" + news_json
            )
            summary = await agent_bridge.send(prompt)
        except Exception as e:
            logger.warning("Agent summarization failed, using fallback: %s", e)

    # Fallback: simple formatted list
    if not summary:
        lines = []
        for a in batch:
            lines.append(f"• [{a.get('source', '?')}] {a.get('title', '')}\n  └ {a['url']}")
        summary = "\n".join(lines)

    # Push message to all subscribers
    header = f"📰 新聞推播 ({len(new_articles)} 則新文章)\n{'=' * 20}\n\n"
    message = header + summary

    for chat_id in subscribers:
        try:
            await bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            logger.error("Failed to push news to %s: %s", chat_id, e)

    # Record pushed articles
    now = datetime.now(timezone.utc).isoformat()
    for article in new_articles:
        pushed_records.append({
            "url": article["url"],
            "title": article.get("title", ""),
            "pushed_at": now,
        })
    _save_pushed_news(pushed_records)
    logger.info("Pushed %d articles to %d subscribers", len(new_articles), len(subscribers))


def _load_pushed_threads() -> list[dict]:
    """Load pushed threads records from JSON file."""
    if not PUSHED_THREADS_PATH.exists():
        return []
    try:
        return json.loads(PUSHED_THREADS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_pushed_threads(records: list[dict]) -> None:
    """Save pushed threads records to JSON file."""
    PUSHED_THREADS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUSHED_THREADS_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _cleanup_expired_threads(records: list[dict]) -> list[dict]:
    """Remove records older than THREADS_TTL_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=THREADS_TTL_DAYS)
    result = []
    for r in records:
        try:
            pushed_at = datetime.fromisoformat(r["pushed_at"])
            if pushed_at.tzinfo is None:
                pushed_at = pushed_at.replace(tzinfo=timezone.utc)
            if pushed_at > cutoff:
                result.append(r)
        except (KeyError, ValueError):
            continue
    return result


def _format_thread_post(post: dict) -> str:
    """Format a single thread post for Telegram message."""
    user = post.get("user", "unknown")
    text = post.get("text", "")
    url = post.get("url", "")
    timestamp = post.get("timestamp", "")

    # Truncate long text
    if len(text) > 500:
        text = text[:497] + "..."

    parts = [f"🧵 Threads - {user}"]
    if timestamp:
        parts[0] += f" ({timestamp[:10]})"
    if text:
        parts.append(text)
    if url:
        parts.append(f"🔗 {url}")
    return "\n".join(parts)


async def threads_push_job(bot, subscription_manager) -> None:
    """Scheduled job: fetch threads, filter, format, push."""
    from tools.fetch_threads import check_new

    logger.info("Threads push job started")

    try:
        result = await check_new()
    except Exception as e:
        logger.error("Failed to fetch threads: %s", e)
        return

    if "error" in result:
        logger.error("Threads fetch error: %s", result["error"])
        return

    posts = result.get("posts", [])
    if not posts:
        logger.info("No new threads posts found")
        return

    # Load and cleanup
    pushed_records = _load_pushed_threads()
    pushed_records = _cleanup_expired_threads(pushed_records)
    pushed_ids = {r["id"] for r in pushed_records}

    # Filter new posts
    new_posts = [p for p in posts if p.get("id") and p["id"] not in pushed_ids]

    if not new_posts:
        logger.info("All threads already pushed")
        _save_pushed_threads(pushed_records)
        return

    # Get subscribers
    subscribers = subscription_manager.get_subscribers("threads")
    if not subscribers:
        logger.info("No threads subscribers")
        now = datetime.now(timezone.utc).isoformat()
        for post in new_posts:
            pushed_records.append({"id": post["id"], "pushed_at": now})
        _save_pushed_threads(pushed_records)
        return

    # Format and push (NO Agent, direct push)
    for post in new_posts:
        message = _format_thread_post(post)
        for chat_id in subscribers:
            try:
                await bot.send_message(chat_id=chat_id, text=message)
            except Exception as e:
                logger.error("Failed to push thread to %s: %s", chat_id, e)

    # Record pushed
    now = datetime.now(timezone.utc).isoformat()
    for post in new_posts:
        pushed_records.append({"id": post["id"], "pushed_at": now})
    _save_pushed_threads(pushed_records)
    logger.info("Pushed %d threads to %d subscribers", len(new_posts), len(subscribers))


def _load_pushed_uanalyze() -> list[dict]:
    """Load pushed UAnalyze report records from JSON file."""
    if not PUSHED_UANALYZE_PATH.exists():
        return []
    try:
        return json.loads(PUSHED_UANALYZE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_pushed_uanalyze(records: list[dict]) -> None:
    """Save pushed UAnalyze report records to JSON file."""
    PUSHED_UANALYZE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUSHED_UANALYZE_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _cleanup_expired_uanalyze(records: list[dict]) -> list[dict]:
    """Remove records older than UANALYZE_TTL_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=UANALYZE_TTL_DAYS)
    result = []
    for r in records:
        try:
            pushed_at = datetime.fromisoformat(r["pushed_at"])
            if pushed_at.tzinfo is None:
                pushed_at = pushed_at.replace(tzinfo=timezone.utc)
            if pushed_at > cutoff:
                result.append(r)
        except (KeyError, ValueError):
            continue
    return result


def _format_uanalyze_report(report: dict) -> str:
    """Format a single UAnalyze report for a Telegram message (plain, no HTML)."""
    stock_code = report.get("stock_code", "")
    stock_name = report.get("stock_name", "")
    title = report.get("title", "")
    date = report.get("date", "")
    summary = report.get("summary", "")

    # Header: 公司名 (代號)
    stock = stock_name
    if stock_code:
        stock = f"{stock_name} ({stock_code})" if stock_name else stock_code
    head = "📋 UAnalyze 新報告"
    if stock:
        head += f" · {stock}"
    parts = [head]

    # Subtitle: 報告主題（日期）
    if title and date:
        parts.append(f"{title}（{date}）")
    elif title or date:
        parts.append(title or date)

    parts.append("━" * 10)
    if summary:
        parts.append(summary[:800])
    return "\n".join(parts)


async def uanalyze_push_job(bot, subscription_manager) -> None:
    """Scheduled job: poll UAnalyze for newly published reports and push them to
    subscribers. Dedup by report id (persisted). No AI, no keyword filtering —
    every new report is pushed with a normal notification."""
    from tools.uanalyze import list_latest_reports

    logger.info("UAnalyze report push job started")

    try:
        result = await list_latest_reports()
    except Exception as e:
        logger.error("Failed to fetch UAnalyze reports: %s", e)
        return

    if "error" in result:
        logger.error("UAnalyze report fetch error: %s", result["error"])
        return

    reports = result.get("reports", [])
    if not reports:
        logger.info("No UAnalyze reports found")
        return

    # Load and cleanup pushed records (dedup by report id).
    pushed_records = _load_pushed_uanalyze()
    pushed_records = _cleanup_expired_uanalyze(pushed_records)
    pushed_ids = {r["id"] for r in pushed_records}

    new_reports = [
        r for r in reports if r.get("id") is not None and r["id"] not in pushed_ids
    ]

    # First run (no state yet): seed dedup state without spamming every old report.
    if not pushed_records and new_reports:
        now = datetime.now(timezone.utc).isoformat()
        for r in reports:
            if r.get("id") is not None:
                pushed_records.append({"id": r["id"], "pushed_at": now})
        _save_pushed_uanalyze(pushed_records)
        logger.info(
            "UAnalyze monitor initialized with %d existing reports", len(pushed_records)
        )
        return

    if not new_reports:
        logger.info("All UAnalyze reports already pushed")
        _save_pushed_uanalyze(pushed_records)
        return

    subscribers = subscription_manager.get_subscribers("uanalyze")
    now = datetime.now(timezone.utc).isoformat()
    if not subscribers:
        logger.info("No UAnalyze subscribers")
        for r in new_reports:
            pushed_records.append({"id": r["id"], "pushed_at": now})
        _save_pushed_uanalyze(pushed_records)
        return

    # Oldest-first so the newest report ends up at the bottom of the chat.
    for report in sorted(new_reports, key=lambda r: r["id"]):
        message = _format_uanalyze_report(report)
        for chat_id in subscribers:
            try:
                await bot.send_message(
                    chat_id=chat_id, text=message, disable_web_page_preview=True
                )
            except Exception as e:
                logger.error("Failed to push UAnalyze report to %s: %s", chat_id, e)

    for r in new_reports:
        pushed_records.append({"id": r["id"], "pushed_at": now})
    _save_pushed_uanalyze(pushed_records)
    logger.info(
        "Pushed %d UAnalyze reports to %d subscribers", len(new_reports), len(subscribers)
    )


def setup_scheduler(bot, subscription_manager, agent_bridge, config: dict, notifier=None) -> AsyncIOScheduler:
    """Create and configure the APScheduler with news and threads push jobs."""
    from bot.error_notify import run_with_retry

    scheduler = AsyncIOScheduler()

    news_interval = config.get("news_schedule_interval_min", 60)
    threads_interval = config.get("threads_schedule_interval_min", 15)
    uanalyze_interval = config.get("uanalyze_schedule_interval_min", 30)

    if notifier:
        # Wrapped jobs with retry + error notification
        async def wrapped_news_job():
            await run_with_retry(news_push_job, "news_push", notifier, bot, subscription_manager, agent_bridge)

        async def wrapped_threads_job():
            await run_with_retry(threads_push_job, "threads_push", notifier, bot, subscription_manager)

        async def wrapped_uanalyze_job():
            await run_with_retry(uanalyze_push_job, "uanalyze_push", notifier, bot, subscription_manager)

        scheduler.add_job(
            wrapped_news_job,
            "interval",
            minutes=news_interval,
            id="news_push",
            name="News Push",
            misfire_grace_time=300,
        )
        scheduler.add_job(
            wrapped_threads_job,
            "interval",
            minutes=threads_interval,
            id="threads_push",
            name="Threads Push",
            misfire_grace_time=120,
        )
        scheduler.add_job(
            wrapped_uanalyze_job,
            "interval",
            minutes=uanalyze_interval,
            id="uanalyze_push",
            name="UAnalyze Report Push",
            misfire_grace_time=300,
        )
    else:
        # Direct jobs (backward compatible, no retry wrapper)
        scheduler.add_job(
            news_push_job,
            "interval",
            minutes=news_interval,
            args=[bot, subscription_manager, agent_bridge],
            id="news_push",
            name="News Push",
            misfire_grace_time=300,
        )
        scheduler.add_job(
            threads_push_job,
            "interval",
            minutes=threads_interval,
            args=[bot, subscription_manager],
            id="threads_push",
            name="Threads Push",
            misfire_grace_time=120,
        )
        scheduler.add_job(
            uanalyze_push_job,
            "interval",
            minutes=uanalyze_interval,
            args=[bot, subscription_manager],
            id="uanalyze_push",
            name="UAnalyze Report Push",
            misfire_grace_time=300,
        )

    logger.info(
        "Scheduler configured: news=%dmin, threads=%dmin, uanalyze=%dmin",
        news_interval,
        threads_interval,
        uanalyze_interval,
    )
    return scheduler
