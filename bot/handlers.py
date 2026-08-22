"""Telegram message handlers."""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "🤖 *台股投資輔助 Bot*\n\n"
    "*訂閱推播*\n"
    "/sub\\_news /unsub\\_news — 訂閱/取消新聞推播（每小時）\n"
    "/sub\\_threads /unsub\\_threads — 訂閱/取消 Threads 推播（每 15 分）\n\n"
    "*即時查詢（直接跑工具，秒回）*\n"
    "/p `<代號>` — 即時股價，例 `/p 2330`\n"
    "/k `<代號> [天數]` — K 線圖，例 `/k 2330 60`\n"
    "/ua `<代號>` — UAnalyze 估值分析，例 `/ua 2330`\n"
    "/news — 立即抓最新新聞\n"
    "/threads — 立即抓 Threads 貼文\n\n"
    "*問 AI（自然語言，會自動組合工具）*\n"
    f"@我 你的問題 — 例：`@bot 台積電最近怎麼樣？`\n\n"
    "輸入 /help 隨時查看本說明。"
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — greet the user and show capabilities."""
    if update.message:
        await update.message.reply_text(
            "👋 歡迎使用台股投資輔助 Bot！\n\n" + HELP_TEXT,
            parse_mode="Markdown",
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — show the command list."""
    if update.message:
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


def _command_arg(update: Update) -> str | None:
    """Extract the first argument after a command, or None."""
    if not update.message or not update.message.text:
        return None
    parts = update.message.text.split()
    return parts[1] if len(parts) > 1 else None


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /p <代號> — fetch real-time price directly (no AI)."""
    symbol = _command_arg(update)
    if not symbol:
        await update.message.reply_text("用法：/p <股票代號>，例 /p 2330")
        return

    from tools.get_stock_price import fetch_price

    try:
        r = await fetch_price(symbol)
    except Exception as e:
        logger.error("/p failed for %s: %s", symbol, e)
        await update.message.reply_text(f"⚠️ 查詢失敗：{e}")
        return

    if "error" in r:
        await update.message.reply_text(f"😕 {r['error']}")
        return

    sign = "🔺" if (r.get("change") or 0) >= 0 else "🔻"
    await update.message.reply_text(
        f"📊 {r.get('name', symbol)} ({r.get('symbol', symbol)})\n"
        f"股價：{r.get('price')}\n"
        f"漲跌：{sign} {r.get('change')} ({r.get('change_pct')}%)\n"
        f"成交量：{r.get('volume')}\n"
        f"來源：{r.get('source')}"
    )


async def kchart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /k <代號> [天數] — draw K-line chart and send as photo (no AI)."""
    symbol = _command_arg(update)
    if not symbol:
        await update.message.reply_text("用法：/k <股票代號> [天數]，例 /k 2330 60")
        return

    period = 60
    parts = update.message.text.split()
    if len(parts) > 2:
        try:
            period = int(parts[2])
        except ValueError:
            pass

    await update.message.reply_text(f"📈 正在繪製 {symbol} 的 K 線圖…")

    from tools.draw_kchart import draw

    try:
        r = await draw(symbol, period)
    except Exception as e:
        logger.error("/k failed for %s: %s", symbol, e)
        await update.message.reply_text(f"⚠️ 繪圖失敗：{e}")
        return

    if "error" in r:
        await update.message.reply_text(f"😕 {r['error']}")
        return

    try:
        with open(r["image_path"], "rb") as f:
            await update.message.reply_photo(photo=f, caption=f"{symbol} K 線圖（{period} 日）")
    except OSError as e:
        logger.error("Failed to send chart image: %s", e)
        await update.message.reply_text("⚠️ 圖片傳送失敗")


async def uanalyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ua <代號> — UAnalyze AI valuation (no local AI; calls UAnalyze service)."""
    symbol = _command_arg(update)
    if not symbol:
        await update.message.reply_text("用法：/ua <股票代號>，例 /ua 2330")
        return

    await update.message.reply_text(f"🧠 正在分析 {symbol}…")

    from tools.uanalyze import analyze

    try:
        r = await analyze(symbol)
    except Exception as e:
        logger.error("/ua failed for %s: %s", symbol, e)
        await update.message.reply_text(f"⚠️ 分析失敗：{e}")
        return

    if "error" in r:
        await update.message.reply_text(f"😕 {r['error']}")
        return

    analysis = r.get("analysis", "")
    if isinstance(analysis, dict):
        import json as _json

        analysis = _json.dumps(analysis, ensure_ascii=False, indent=2)
    await update.message.reply_text(f"🧠 {symbol} UAnalyze 分析\n{'=' * 20}\n{analysis}")


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
    application.add_handler(CommandHandler("start", start_command), group=0)
    application.add_handler(CommandHandler("help", help_command), group=0)
    application.add_handler(CommandHandler("p", price_command), group=0)
    application.add_handler(CommandHandler("k", kchart_command), group=0)
    application.add_handler(CommandHandler("ua", uanalyze_command), group=0)
    application.add_handler(
        MessageHandler(filters.Entity("mention"), mention), group=0
    )
    logger.info("Handlers registered.")
