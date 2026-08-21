"""Taiwan Stock Investment Telegram Bot - Entry Point."""

import logging
import os

from dotenv import load_dotenv
from telegram.ext import Application

from bot.handlers import register_handlers

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment")

    logger.info("Starting bot...")
    application = Application.builder().token(token).build()
    register_handlers(application)
    logger.info("Bot started. Polling...")
    application.run_polling()


if __name__ == "__main__":
    main()
