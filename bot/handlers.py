"""Telegram message handlers."""

import asyncio
import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from bot.reply_format import parse_reply_format

logger = logging.getLogger(__name__)


def _show_agent_tools() -> bool:
    """Whether to append the "tools used" line to @mention replies.

    Defaults to True (dev-friendly). Set SHOW_AGENT_TOOLS=0/false/no to turn
    off in production without a code change.
    """
    return os.getenv("SHOW_AGENT_TOOLS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )

HELP_TEXT = (
    "🤖 *台股投資輔助 Bot*\n\n"
    "*訂閱推播*\n"
    "/sub\\_news /unsub\\_news — 訂閱/取消新聞推播（每小時）\n"
    "/sub\\_ua\\_reports /unsub\\_ua\\_reports — 訂閱/取消 UAnalyze 新研究報告推播（每 30 分）\n\n"
    "*即時查詢（直接跑工具，秒回）*\n"
    "/p `<代號>` — 即時股價＋盤中分時走勢圖（附基本面：本益比/最新財報等），例 `/p 2330`\n"
    "/k `<代號> [天數]` — K 線圖，例 `/k 2330 60`\n"
    "*問 AI（自然語言，會自動組合工具）*\n"
    "/ask `<問題>` — 例：`/ask 台積電最近怎麼樣？`（估值/新聞/法人/財報等都問得到，群組、私訊皆可）\n\n"
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

    from tools.analysis.get_stock_price import fetch_price

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
    lines = [
        f"📊 {r.get('name', symbol)} ({r.get('symbol', symbol)})",
        f"股價：{r.get('price')}",
        f"漲跌：{sign} {r.get('change')} ({r.get('change_pct')}%)",
        f"成交量：{r.get('volume')}",
        f"來源：{r.get('source')}",
    ]

    # best-effort 基本面（UAnalyze）：有才多列，沒有就維持原本價量輸出。
    fundamentals = r.get("fundamentals")
    if fundamentals:
        lines.append("— 基本面 —")
        for label, value in fundamentals.items():
            lines.append(f"{label}：{value}")

    await update.message.reply_text("\n".join(lines))

    # 價量回完後，best-effort 再附上盤中分時走勢圖（失敗絕不影響上面的價量回傳）。
    await _send_intraday_chart(update, symbol)


async def _send_intraday_chart(update: Update, symbol: str) -> None:
    """Best-effort：畫盤中分時走勢圖並以 photo 回覆。

    這是 /p 的加分項，任何失敗（無資料、繪圖錯、傳圖錯）都只記 log、不丟出，
    確保價量文字回覆已送出、使用者體驗不受影響。
    """
    try:
        from tools.analysis.draw_intraday_chart import draw as draw_intraday

        r = await draw_intraday(symbol)
        if "error" in r:
            logger.debug("intraday chart skipped for %s: %s", symbol, r["error"])
            return
        with open(r["image_path"], "rb") as f:
            await update.message.reply_photo(
                photo=f, caption=f"{symbol} 盤中分時走勢"
            )
    except Exception as e:
        logger.debug("intraday chart augment skipped for %s: %s", symbol, e)


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

    from tools.analysis.draw_kchart import draw

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

async def _send_agent_reply(
    update: Update, reply: str, tools_line: str = ""
) -> None:
    """把 Agent 回覆送到 Telegram，由 Agent 用第一行 FORMAT 標記自選呈現方式。

    - text（預設）：純文字訊息；超過 Telegram 4096 字元上限時自動分段多則送出。
    - html：把內文包成完整 HTML5 文件（含 CSS），用 reply_document 傳 .html 附件。
    - markdown：把內文寫成 .md，用 reply_document 傳附件。
    檔案模式不受 4096 字元限制，適合放寬面向後的完整分析報告。

    工具清單（開發用）：text 直接附在訊息尾；檔案模式附在檔案內容尾（HTML 用 <pre>、
    markdown 用 code fence）。
    安全網：檔案傳送若失敗，退回純文字分段送，確保使用者一定收得到內容。
    """
    mode, body = parse_reply_format(reply)

    if mode in ("html", "markdown"):
        try:
            await _send_document_reply(update, mode, body, tools_line)
            return
        except Exception as e:  # noqa: BLE001 — 傳檔失敗一律退回純文字
            logger.warning("%s 檔案送出失敗，退回純文字：%s", mode, e)
            body = f"{body}\n\n（附件產生失敗，改以純文字呈現）"

    # 純文字（預設，或檔案模式的 fallback）。
    text = body if mode in ("html", "markdown") else reply
    if tools_line:
        text = f"{text}\n\n{tools_line}"
    await _send_long_text(update, text)


async def _send_document_reply(
    update: Update, mode: str, body: str, tools_line: str
) -> None:
    """把內文包成 .html / .md 檔案，用 reply_document 傳附件。"""
    import io

    from bot.reply_docs import (
        build_html_document,
        build_markdown_document,
        safe_filename,
        title_from_body,
    )

    # 先從原始內文抓標題（在附加工具清單之前），讓檔名看得出內容。
    title = title_from_body(body, mode)
    stem = title or "stock_report"

    if mode == "html":
        if tools_line:
            body = f"{body}\n<pre>{_html_escape(tools_line)}</pre>"
        content = build_html_document(body, title=title or "台股分析報告")
        filename = safe_filename(stem, "html")
    else:  # markdown
        if tools_line:
            body = f"{body}\n\n```\n{tools_line}\n```"
        content = build_markdown_document(body)
        filename = safe_filename(stem, "md")

    buffer = io.BytesIO(content.encode("utf-8"))
    buffer.name = filename
    await update.message.reply_document(document=buffer, filename=filename)


async def _send_long_text(update: Update, text: str) -> None:
    """純文字送出；超過 Telegram 上限時在換行邊界分段多則送。"""
    limit = 4000  # 保留餘裕（Telegram 硬上限 4096）
    if len(text) <= limit:
        await update.message.reply_text(text)
        return

    # 盡量在換行處切，避免切斷句子。
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunk, remaining = remaining, ""
        else:
            cut = remaining.rfind("\n", 0, limit)
            if cut <= 0:
                cut = limit
            chunk, remaining = remaining[:cut], remaining[cut:].lstrip("\n")
        await update.message.reply_text(chunk)


def _html_escape(text: str) -> str:
    """最小 HTML 跳脫（< > &），供 HTML 附件內嵌工具清單用。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ask <question> — route the question to the Agent.

    Works identically in private chats and groups (no @mention needed).
    """
    if not update.message:
        return

    text_after = (update.message.text or "").partition(" ")[2].strip()
    if not text_after:
        await update.message.reply_text(
            "用法：/ask 你的問題，例如 `/ask 台積電最近怎麼樣`",
            parse_mode="Markdown",
        )
        return

    logger.info(
        "/ask by user %s: %s",
        update.effective_user.id if update.effective_user else "unknown",
        text_after,
    )

    bridge = context.bot_data.get("agent_bridge")
    if not bridge:
        await update.message.reply_text("⚠️ Agent 未設定")
        return

    try:
        from agent.conversation_log import log_conversation
        from agent.prompts import build_mention_prompt
        from agent.bridge import diff_quota, format_quota_line
        from agent import quota_ledger

        prompt = build_mention_prompt(text_after)

        # 額度查詢要另跑一次 agy（數秒），與主要呼叫**並行**，不加長等待時間。
        # 只在要顯示時才查；失敗不影響回覆（fetch_usage_limits 自己吞例外回 []）。
        if _show_agent_tools():
            quota_task = asyncio.create_task(bridge.fetch_usage_limits())
        else:
            quota_task = None

        try:
            result = await bridge.send_detailed(prompt)
        except BaseException:
            if quota_task:
                quota_task.cancel()
            raise

        # Persist the full exchange (question + answer + tools used).
        log_conversation(
            question=text_after,
            result=result,
            user_id=(
                update.effective_user.id if update.effective_user else None
            ),
            chat_id=(
                update.effective_chat.id if update.effective_chat else None
            ),
        )

        reply = result.response
        tools_line = ""
        if _show_agent_tools():
            quota_line = ""
            try:
                # 呼叫前的額度（並行取，已跑完）＋呼叫後再取一次：
                # 後者才含這一輪的消耗，兩者相減得「本次用掉多少」。
                before = await quota_task if quota_task else []
                after = await bridge.fetch_usage_limits()
                quota_line = format_quota_line(diff_quota(before, after) or before)
                # 記帳並用歷史校準估「本次佔額度幾 %」（整數百分比看不出來的部分）。
                # 連 before 一起記，本輪造成的下降才能立刻成為校準樣本。
                tokens = (result.usage or {}).get("total_tokens") or 0
                quota_ledger.record(tokens, after, before=before)
                estimate = quota_ledger.estimate_line(tokens, after)
                if estimate:
                    quota_line = f"{quota_line}\n{estimate}" if quota_line else estimate
            except Exception as e:  # 額度只是附加資訊，壞了就不顯示
                logger.debug("quota line failed: %s", e)
            # 工具清單 + token 用量 + 額度（同一個開發用開關控制）
            tools_line = "\n\n".join(
                p
                for p in (result.tools_line(), result.usage_line(), quota_line)
                if p
            )
        await _send_agent_reply(update, reply, tools_line)
    except TimeoutError:
        await update.message.reply_text("⚠️ Agent 暫時無法回應，請稍後再試")
    except RuntimeError as e:
        logger.error("Agent error: %s", e)
        await update.message.reply_text("⚠️ Agent 發生錯誤，請稍後再試")


def register_handlers(application: Application) -> None:
    """Register all message handlers."""
    application.add_handler(CommandHandler("start", start_command), group=0)
    application.add_handler(CommandHandler("help", help_command), group=0)
    application.add_handler(CommandHandler("p", price_command), group=0)
    application.add_handler(CommandHandler("k", kchart_command), group=0)
    application.add_handler(CommandHandler("ask", ask_command), group=0)
    logger.info("Handlers registered.")
