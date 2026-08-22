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


async def mention(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detect @bot_username mentions and route to Agent."""
    if not update.message or not update.message.entities:
        return

    bot_username = context.bot.username
    for entity in update.message.entities:
        if entity.type == "mention":
            mentioned = update.message.text[entity.offset : entity.offset + entity.length]
            if mentioned.lower() == f"@{bot_username}".lower():
                text_after = update.message.text[entity.offset + entity.length :].strip()
                if not text_after:
                    await update.message.reply_text("請在 @mention 後加上您的問題")
                    return

                logger.info(
                    "Bot mentioned by user %s: %s",
                    update.effective_user.id if update.effective_user else "unknown",
                    text_after,
                )

                bridge = context.bot_data.get("agent_bridge")
                if not bridge:
                    await update.message.reply_text("⚠️ Agent 未設定")
                    return

                try:
                    from agent.prompts import build_mention_prompt

                    prompt = build_mention_prompt(text_after)
                    response = await bridge.send(prompt)
                    await update.message.reply_text(response)
                except TimeoutError:
                    await update.message.reply_text("⚠️ Agent 暫時無法回應，請稍後再試")
                except RuntimeError as e:
                    logger.error("Agent error: %s", e)
                    await update.message.reply_text("⚠️ Agent 發生錯誤，請稍後再試")
                return


def register_handlers(application: Application) -> None:
    """Register all message handlers."""
    application.add_handler(
        MessageHandler(filters.Entity("mention"), mention), group=0
    )
    logger.info("Handlers registered.")
