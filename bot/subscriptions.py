"""Subscription management for news and threads push notifications."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)

DEFAULT_PATH = "data/subscriptions.json"


class SubscriptionManager:
    """Manages user subscriptions to news and threads channels.

    Persists state to a JSON file on disk.
    """

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._data: dict[str, list[dict]] = self._load()

    def _load(self) -> dict[str, list[dict]]:
        """Read subscriptions from disk. Create empty structure if file doesn't exist."""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info("Loaded subscriptions from %s", self._path)
                return data
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load subscriptions, starting fresh: %s", e)
        return {"news": [], "threads": []}

    def _save(self) -> None:
        """Write current subscriptions to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        logger.debug("Saved subscriptions to %s", self._path)

    def subscribe(self, chat_id: int, channel: str) -> bool:
        """Add a chat_id to a channel's subscription list.

        Returns True if newly added, False if already subscribed.
        """
        if channel not in self._data:
            self._data[channel] = []

        # Check for duplicate
        for entry in self._data[channel]:
            if entry["chat_id"] == chat_id:
                return False

        self._data[channel].append({
            "chat_id": chat_id,
            "subscribed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        self._save()
        logger.info("User %d subscribed to %s", chat_id, channel)
        return True

    def unsubscribe(self, chat_id: int, channel: str) -> bool:
        """Remove a chat_id from a channel's subscription list.

        Returns True if removed, False if wasn't subscribed.
        """
        if channel not in self._data:
            return False

        original_len = len(self._data[channel])
        self._data[channel] = [
            entry for entry in self._data[channel] if entry["chat_id"] != chat_id
        ]

        if len(self._data[channel]) < original_len:
            self._save()
            logger.info("User %d unsubscribed from %s", chat_id, channel)
            return True
        return False

    def get_subscribers(self, channel: str) -> list[int]:
        """Return list of chat_ids subscribed to a channel."""
        return [entry["chat_id"] for entry in self._data.get(channel, [])]


# Module-level manager instance
manager = SubscriptionManager()


async def sub_news_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sub_news command."""
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    if manager.subscribe(chat_id, "news"):
        await update.message.reply_text("✅ 已訂閱新聞推播")
    else:
        await update.message.reply_text("ℹ️ 您已經訂閱新聞推播")


async def unsub_news_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unsub_news command."""
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    if manager.unsubscribe(chat_id, "news"):
        await update.message.reply_text("✅ 已取消新聞推播")
    else:
        await update.message.reply_text("ℹ️ 您尚未訂閱新聞推播")


async def sub_threads_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sub_threads command."""
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    if manager.subscribe(chat_id, "threads"):
        await update.message.reply_text("✅ 已訂閱 Threads 推播")
    else:
        await update.message.reply_text("ℹ️ 您已經訂閱 Threads 推播")


async def unsub_threads_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unsub_threads command."""
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    if manager.unsubscribe(chat_id, "threads"):
        await update.message.reply_text("✅ 已取消 Threads 推播")
    else:
        await update.message.reply_text("ℹ️ 您尚未訂閱 Threads 推播")


async def news_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /news command — fetch latest news and reply to the caller immediately.

    Unlike the scheduled push, this always shows the caller the fetched
    headlines directly (no subscription or dedup filtering), so it works as a
    live "is it fetching?" check.
    """
    if not update.effective_chat:
        return

    await update.message.reply_text("🔍 正在抓取最新新聞…")

    from tools.fetch_news import latest

    try:
        result = await latest()
        articles = result.get("articles", []) if isinstance(result, dict) else result
    except Exception as e:
        logger.error("Manual /news fetch failed: %s", e)
        await update.message.reply_text(f"⚠️ 抓取新聞時發生錯誤：{e}")
        return

    if not articles:
        await update.message.reply_text("😕 目前沒有抓到任何新聞")
        return

    # Optionally summarize via Agent; fall back to a plain list.
    batch = articles[:10]
    bridge = context.bot_data.get("agent_bridge")
    summary = None
    if bridge:
        try:
            import json as _json

            news_json = _json.dumps(
                [{"title": a.get("title", ""), "source": a.get("source", ""), "url": a["url"]} for a in batch],
                ensure_ascii=False,
            )
            prompt = (
                "請用繁體中文摘要以下新聞，每則一行，"
                "格式「• [來源] 標題摘要\\n  └ URL」：\n" + news_json
            )
            summary = await bridge.send(prompt)
        except Exception as e:
            logger.warning("Agent summarization failed for /news, using fallback: %s", e)

    if not summary:
        lines = []
        for a in batch:
            lines.append(f"• [{a.get('source', '?')}] {a.get('title', '')}\n  └ {a['url']}")
        summary = "\n".join(lines)

    header = f"📰 最新新聞 ({len(batch)} 則)\n{'=' * 20}\n\n"
    await update.message.reply_text(header + summary, disable_web_page_preview=True)


async def threads_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /threads command — fetch latest Threads posts and reply immediately.

    Like /news, this always shows the caller the fetched posts directly
    (no subscription or dedup filtering), as a live "is it fetching?" check.
    """
    if not update.effective_chat:
        return

    await update.message.reply_text("🔍 正在抓取最新 Threads 貼文…")

    from bot.scheduler import _format_thread_post
    from tools.fetch_threads import check_new

    try:
        result = await check_new()
    except Exception as e:
        logger.error("Manual /threads fetch failed: %s", e)
        await update.message.reply_text(f"⚠️ 抓取 Threads 時發生錯誤：{e}")
        return

    if "error" in result:
        await update.message.reply_text(f"⚠️ {result['error']}")
        return

    posts = result.get("posts", [])
    if not posts:
        await update.message.reply_text("😕 目前沒有抓到任何 Threads 貼文")
        return

    for post in posts[:10]:
        await update.message.reply_text(
            _format_thread_post(post), disable_web_page_preview=True
        )


def register_subscription_handlers(application: Application) -> None:
    """Register subscription command handlers."""
    application.add_handler(CommandHandler("sub_news", sub_news_handler))
    application.add_handler(CommandHandler("unsub_news", unsub_news_handler))
    application.add_handler(CommandHandler("sub_threads", sub_threads_handler))
    application.add_handler(CommandHandler("unsub_threads", unsub_threads_handler))
    application.add_handler(CommandHandler("news", news_now_handler))
    application.add_handler(CommandHandler("threads", threads_now_handler))
    logger.info("Subscription handlers registered.")
