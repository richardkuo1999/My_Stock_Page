"""Telegram message handlers."""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user message back."""
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)


async def mention(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detect @bot_username mentions and log them.

    Actual agent integration will be implemented in Ticket 03.
    """
    if not update.message or not update.message.entities:
        return

    bot_username = context.bot.username
    for entity in update.message.entities:
        if entity.type == "mention":
            mentioned = update.message.text[entity.offset : entity.offset + entity.length]
            if mentioned.lower() == f"@{bot_username}".lower():
                text_after = update.message.text[entity.offset + entity.length :].strip()
                logger.info(
                    "Bot mentioned by user %s: %s",
                    update.effective_user.id if update.effective_user else "unknown",
                    text_after,
                )
                # TODO: Ticket 03 - route to AgentBridge
                break


def register_handlers(application: Application) -> None:
    """Register all message handlers."""
    # Mention handler has higher priority (group 0)
    application.add_handler(
        MessageHandler(filters.Entity("mention"), mention), group=0
    )
    # Echo handler (group 1, lower priority)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, echo), group=1
    )
    logger.info("Handlers registered.")
