"""Taiwan Stock Investment Telegram Bot - Entry Point."""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram.ext import Application

from agent.bridge import AntigravityCLIBridge
from bot.handlers import register_handlers
from bot.scheduler import setup_scheduler
from bot.subscriptions import manager as subscription_manager
from bot.subscriptions import register_subscription_handlers

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
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

    application = Application.builder().token(token).build()

    # Components
    bridge = AntigravityCLIBridge()

    # Store in bot_data for handlers
    application.bot_data["agent_bridge"] = bridge
    application.bot_data["subscription_manager"] = subscription_manager

    # Register handlers
    register_handlers(application)
    register_subscription_handlers(application)

    # Setup scheduler
    scheduler = setup_scheduler(application.bot, subscription_manager, bridge, config)

    # Lifecycle hooks
    async def post_init(app):
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
