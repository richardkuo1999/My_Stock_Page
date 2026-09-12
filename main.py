"""Taiwan Stock Investment Telegram Bot - Entry Point."""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import Application

from agent.bridge import AntigravityCLIBridge
from bot.error_notify import JobErrorNotifier
from bot.handlers import register_handlers
from bot.logging_conf import setup_logging
from bot.scheduler import setup_scheduler
from bot.subscriptions import manager as subscription_manager
from bot.subscriptions import register_subscription_handlers

load_dotenv()

setup_logging()
logger = logging.getLogger(__name__)


def _load_config() -> dict:
    """Load configuration from config.json."""
    config_path = Path("config.json")
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load config.json: %s", e)
    return {}


def main() -> None:
    """Start the bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment")

    config = _load_config()
    logger.info("Starting bot...")

    # concurrent_updates(True)：允許同時處理多個 update（預設值 1 會序列化，導致
    # 同時發多個 /ask 只能一個一個跑）。無上限——每個 /ask 各開獨立 agy 子程序並行；
    # 若日後資源吃緊（記憶體 / agy rate limit）再改成有上限的整數。
    application = (
        Application.builder().token(token).concurrent_updates(True).build()
    )

    # Components
    bridge = AntigravityCLIBridge()

    # Store in bot_data for handlers
    application.bot_data["agent_bridge"] = bridge
    application.bot_data["subscription_manager"] = subscription_manager

    # Register handlers
    register_handlers(application)
    register_subscription_handlers(application)

    # Setup scheduler
    notifier = JobErrorNotifier(bot=application.bot)
    scheduler = setup_scheduler(application.bot, subscription_manager, bridge, config, notifier)

    # Application-level error handler: catches unhandled exceptions raised inside
    # any handler (e.g. @mention routing) so python-telegram-bot no longer logs
    # "No error handlers are registered". Logs the error, tries to reply to the
    # user, and notifies the admin.
    async def error_handler(update, context) -> None:
        logger.error("Unhandled exception in handler", exc_info=context.error)

        # Best-effort user-facing reply
        try:
            if update and getattr(update, "effective_message", None):
                await update.effective_message.reply_text(
                    "⚠️ 系統發生錯誤，請稍後再試"
                )
        except Exception:
            logger.exception("Failed to send error reply to user")

        # Notify admin (reuse the scheduler's notifier)
        try:
            notifier.record_failure("telegram_handler")
            await notifier.notify_admin("telegram_handler", str(context.error))
        except Exception:
            logger.exception("Failed to notify admin about handler error")

    application.add_error_handler(error_handler)

    # Lifecycle hooks
    async def post_init(app):
        # Register the command list so Telegram shows autocomplete suggestions.
        from telegram import BotCommand

        await app.bot.set_my_commands(
            [
                BotCommand("ask", "問 AI（自然語言），例 /ask 台積電最近怎麼樣"),
                BotCommand("p", "即時股價＋分時圖，例 /p 2330"),
                BotCommand("k", "K 線圖，例 /k 2330 60"),
                BotCommand("sub_news", "訂閱新聞推播（每小時）"),
                BotCommand("unsub_news", "取消新聞推播"),
                BotCommand("sub_ua_reports", "訂閱 UAnalyze 新報告推播"),
                BotCommand("unsub_ua_reports", "取消 UAnalyze 報告推播"),
                BotCommand("help", "顯示指令與功能說明"),
            ]
        )
        scheduler.start()
        logger.info("Scheduler started")

    async def post_shutdown(app):
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    application.post_init = post_init
    application.post_shutdown = post_shutdown

    logger.info("Bot started. Polling...")
    application.run_polling()


if __name__ == "__main__":
    main()
