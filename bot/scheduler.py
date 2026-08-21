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


def setup_scheduler(bot, subscription_manager, agent_bridge, config: dict) -> AsyncIOScheduler:
    """Create and configure the APScheduler with news push job."""
    scheduler = AsyncIOScheduler()
    interval_min = config.get("news_schedule_interval_min", 60)

    scheduler.add_job(
        news_push_job,
        "interval",
        minutes=interval_min,
        args=[bot, subscription_manager, agent_bridge],
        id="news_push",
        name="News Push",
        misfire_grace_time=300,
    )

    logger.info("Scheduler configured: news push every %d min", interval_min)
    return scheduler
