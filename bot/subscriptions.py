"""Subscription management for news push notifications."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logger = logging.getLogger(__name__)

DEFAULT_PATH = "data/subscriptions.json"


class SubscriptionManager:
    """Manages user subscriptions to push notification channels.

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
        return {"news": []}

    def _save(self) -> None:
        """Write current subscriptions to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        logger.debug("Saved subscriptions to %s", self._path)

    def subscribe(self, chat_id: int, channel: str, thread_id: int | None = None) -> bool:
        """Add a (chat_id, thread_id) subscription to a channel.

        thread_id identifies a forum topic (message_thread_id) inside a group;
        None means the group's General thread (or a private chat).
        Returns True if newly added, False if already subscribed.
        """
        if channel not in self._data:
            self._data[channel] = []

        # Check for duplicate (composite key: chat_id + thread_id).
        # Legacy entries without a thread_id field are treated as thread_id=None.
        for entry in self._data[channel]:
            if entry["chat_id"] == chat_id and entry.get("thread_id") == thread_id:
                return False

        self._data[channel].append({
            "chat_id": chat_id,
            "thread_id": thread_id,
            "subscribed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        self._save()
        logger.info("User %d (thread %s) subscribed to %s", chat_id, thread_id, channel)
        return True

    def unsubscribe(self, chat_id: int, channel: str, thread_id: int | None = None) -> bool:
        """Remove a (chat_id, thread_id) subscription from a channel.

        Legacy entries without a thread_id field are treated as thread_id=None.
        Returns True if removed, False if wasn't subscribed.
        """
        if channel not in self._data:
            return False

        original_len = len(self._data[channel])
        self._data[channel] = [
            entry
            for entry in self._data[channel]
            if not (entry["chat_id"] == chat_id and entry.get("thread_id") == thread_id)
        ]

        if len(self._data[channel]) < original_len:
            self._save()
            logger.info(
                "User %d (thread %s) unsubscribed from %s", chat_id, thread_id, channel
            )
            return True
        return False

    def get_subscribers(self, channel: str) -> list[tuple[int, int | None]]:
        """Return list of (chat_id, thread_id) subscribed to a channel.

        thread_id is None for General-thread / private-chat subscriptions,
        including legacy entries that predate topic support.
        """
        return [
            (entry["chat_id"], entry.get("thread_id"))
            for entry in self._data.get(channel, [])
        ]


# Module-level manager instance
manager = SubscriptionManager()


def _thread_id(update: Update) -> int | None:
    """Extract the forum topic id (message_thread_id) from an update.

    Returns None for private chats and the group's General thread, so those
    subscriptions collapse to the (chat_id, None) key — backward compatible
    with pre-topic data. Callers reach this only after confirming the update
    carries a message, so we read message_thread_id directly.
    """
    return update.message.message_thread_id


async def sub_news_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sub_news command."""
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    if manager.subscribe(chat_id, "news", thread_id=_thread_id(update)):
        await update.message.reply_text("✅ 已訂閱新聞推播")
    else:
        await update.message.reply_text("ℹ️ 您已經訂閱新聞推播")


async def unsub_news_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unsub_news command."""
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    if manager.unsubscribe(chat_id, "news", thread_id=_thread_id(update)):
        await update.message.reply_text("✅ 已取消新聞推播")
    else:
        await update.message.reply_text("ℹ️ 您尚未訂閱新聞推播")


async def sub_uanalyze_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sub_ua_reports — subscribe to UAnalyze new-report push."""
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    if manager.subscribe(chat_id, "uanalyze", thread_id=_thread_id(update)):
        await update.message.reply_text("✅ 已訂閱 UAnalyze 新報告推播")
    else:
        await update.message.reply_text("ℹ️ 您已經訂閱 UAnalyze 新報告推播")


async def unsub_uanalyze_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unsub_ua_reports — unsubscribe from UAnalyze new-report push."""
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    if manager.unsubscribe(chat_id, "uanalyze", thread_id=_thread_id(update)):
        await update.message.reply_text("✅ 已取消 UAnalyze 新報告推播")
    else:
        await update.message.reply_text("ℹ️ 您尚未訂閱 UAnalyze 新報告推播")


def _news_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the /news source-selection keyboard (全部 + 16 sources, 3 per row)."""
    from tools.fetch_news import SOURCES

    buttons = [InlineKeyboardButton("📚 全部來源", callback_data="news:all")]
    buttons += [
        InlineKeyboardButton(s["name"], callback_data=f"news:{i}")
        for i, s in enumerate(SOURCES)
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    return InlineKeyboardMarkup(rows)


async def news_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /news command — show a source-selection menu. The actual fetch runs
    when the user picks a source (see news_source_callback)."""
    if not update.effective_chat:
        return

    await update.message.reply_text(
        "📰 想看哪個來源的新聞？請選擇：",
        reply_markup=_news_menu_keyboard(),
    )


async def news_source_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a /news source-menu button press: fetch and show that source (or all),
    or return to the menu when the back button is pressed."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    from tools.fetch_news import SOURCES

    choice = query.data.split(":", 1)[1]

    # Back button: news:back → re-show the source menu.
    if choice == "back":
        await query.edit_message_text(
            "📰 想看哪個來源的新聞？請選擇：",
            reply_markup=_news_menu_keyboard(),
        )
        return

    source_name = None
    if choice != "all":
        try:
            source_name = SOURCES[int(choice)]["name"]
        except (ValueError, IndexError):
            await query.edit_message_text("⚠️ 無效的來源")
            return

    label = source_name or "全部來源"
    await query.edit_message_text(f"🔍 正在抓取 {label} 的最新新聞…")

    from tools.fetch_news import _diversify_by_source, latest

    try:
        result = await latest()
        articles = result.get("articles", []) if isinstance(result, dict) else result
    except Exception as e:
        logger.error("/news fetch failed: %s", e)
        await query.edit_message_text(f"⚠️ 抓取新聞時發生錯誤：{e}")
        return

    # Filter to the chosen source, or diversify across all.
    if source_name:
        batch = [a for a in articles if a.get("source") == source_name][:10]
    else:
        batch = _diversify_by_source(articles, 10)

    if not batch:
        await query.edit_message_text(f"😕 {label} 目前沒有新聞")
        return

    bridge = context.bot_data.get("agent_bridge")
    summary = None
    if bridge:
        try:
            news_json = json.dumps(
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
        lines = [
            f"• [{a.get('source', '?')}] {a.get('title', '')}\n  └ {a['url']}"
            for a in batch
        ]
        summary = "\n".join(lines)

    header = f"📰 {label} 最新新聞 ({len(batch)} 則)\n{'=' * 20}\n\n"
    back = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ 選其他來源", callback_data="news:back")]]
    )
    await query.edit_message_text(
        (header + summary)[:4096], disable_web_page_preview=True, reply_markup=back
    )


def register_subscription_handlers(application: Application) -> None:
    """Register subscription command handlers."""
    application.add_handler(CommandHandler("sub_news", sub_news_handler))
    application.add_handler(CommandHandler("unsub_news", unsub_news_handler))
    application.add_handler(CommandHandler("sub_ua_reports", sub_uanalyze_handler))
    application.add_handler(CommandHandler("unsub_ua_reports", unsub_uanalyze_handler))
    application.add_handler(CommandHandler("news", news_now_handler))
    application.add_handler(
        CallbackQueryHandler(news_source_callback, pattern=r"^news:")
    )
    logger.info("Subscription handlers registered.")
