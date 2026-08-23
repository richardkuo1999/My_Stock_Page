"""Telegram message handlers."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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
    "/sub\\_threads /unsub\\_threads — 訂閱/取消 Threads 推播（每 15 分）\n"
    "/sub\\_ua\\_reports /unsub\\_ua\\_reports — 訂閱/取消 UAnalyze 新研究報告推播（每 30 分）\n\n"
    "*即時查詢（直接跑工具，秒回）*\n"
    "/p `<代號>` — 即時股價，例 `/p 2330`\n"
    "/k `<代號> [天數]` — K 線圖，例 `/k 2330 60`\n"
    "/ua `<代號>` — UAnalyze 估值分析，例 `/ua 2330`\n"
    "/data `<代號>` — 法人共識/財務指標/供應鏈/訂單能見度選單，例 `/data 2330`\n"
    "/news — 立即抓最新新聞\n"
    "/threads — 立即抓 Threads 貼文\n\n"
    "*問 AI（自然語言，會自動組合工具）*\n"
    f"@我 你的問題 — 例：`@bot 台積電最近怎麼樣？`\n\n"
    "輸入 /help 隨時查看本說明。"
)

# UAnalyze 分析面向選單。每項為 (按鈕標籤, 實際送出的完整 prompt)。
# 標籤用於 inline 按鈕（需短），送出時用完整 prompt。取自 old_file 的 PROMPT_LIST（33 項全保留）。
UA_PROMPTS: list[tuple[str, str]] = [
    ("近況發展", "近況發展"),
    ("產業趨勢", "產業趨勢"),
    ("產品線分析", "產品線分析"),
    ("長短期展望", "長短期展望"),
    ("供需分析", "供需分析"),
    ("觀察重點", "觀察重點"),
    ("利多因素", "利多因素"),
    ("利空因素", "利空因素"),
    ("接單狀況", "接單狀況"),
    ("資本支出", "資本支出"),
    ("新產品", "新產品"),
    ("時間表", "時間表"),
    ("相關公司", "相關公司"),
    ("同業競爭", "同業競爭"),
    ("護城河分析", "護城河分析"),
    ("併購分析", "併購分析"),
    ("重要數字", "重要數字"),
    ("公司概覽", "公司概覽"),
    ("銷售地區", "銷售地區"),
    ("描述庫存", "描述庫存"),
    (
        "營收成長來源",
        "驅動銷售金額(營收)成長或衰退的來源有哪些，詳細且完整的敍述原因(敍述時請用數據佐證你的論點(若有數據的話))，分為短期(意為持續性不強)、長期(意為持續不斷的動能)",
    ),
    (
        "獲利成長因子",
        "驅動獲利(盈餘)成長或衰退的因子有哪些，詳細且完整的敍述原因(敍述時請用數據佐證你的論點(若有數據的話))，分為短期(意為持續性不強)、長期(意為持續不斷的動能)",
    ),
    (
        "毛利率變化",
        "驅動毛利率(成本)上升或下降的因素有哪些，詳細且完整的敍述原因，可以的話用數據佐證你的論點，分為短期長期。如果資料不足允許提供較少內容，如果資料中找不到原因可以不提供。備註，業外不會影響毛利率，ASP與毛利率不一定相關",
    ),
    (
        "營收時間線",
        "根據資料，將有提到(營收)或(銷售)的資訊取出，重新改寫(改寫程度大)，理為時間線(依時間排序)(去除相同內容)(排除匯兌收益、EPS、毛利率相關資訊)",
    ),
    (
        "展望上下修",
        "法人或公司有展望上下修原因是什麼?請注意要有明確看法變化|調整的意思才算。以多層結構顯示，第1層先[[展望上修(正向調整)]]再<<展望下修(負向調整)>>，第2層 - 時間(例如2025年第一季)、 - 第3層類型(例如<<毛利率下修>>、[[出貨量上修]]以及其他類型)。注意，有上下修的才算，維持不變的不用顯示。如果沒有上下修相關資料，請回答『無相關資料』",
    ),
    (
        "關稅/生產基地",
        "請你幫我做2件事，第一、我提供的資料中是否有提到關稅、貿易戰、或相關細節內容(這很重要一定要找出來)...； 第二、提供公司的生產基地、工廠地點、據點的相關細節內容...",
    ),
    (
        "供應鏈重組",
        "請檢查提供的資料中是否有提到『供應鏈如何重組』、『美國製造基地資訊』、『關稅影響利潤及價格上漲議題』或者『對等關稅影響』的相關內容...如果回答時有相似內容請將其整合為一句，儘量提供具體數據以及具體案例來輔助說明...",
    ),
    (
        "匯率影響",
        "台幣兌美元升貶值對公司成本或競爭力(產業競爭程度如何)的影響(再分為升值 and 貶值)公司說明(如果有的話)及分析並綜合評估影響明顯程度，台幣兌美元升貶值對匯兌損益影響...。輸出：台幣升值情境分析：... 台幣貶值情境分析：...。記得標示正面和負面標記",
    ),
    (
        "AI 相關",
        "請檢查我提供的資料中是否有提到『AI』『邊緣AI』『人工智慧』『人工智能』或相關內容...如果回答時有相似內容請將其整合為一句，可以提供具體數據以及具體案例來輔助說明...",
    ),
    ("新產品進度", "有新產品嗎，進度如何，最後條列出新產品詳細數字"),
    (
        "資本支出細節",
        "詳述資本支出或擴產計劃，包含前因後果、項目、產能、金額、時間點、地點，若無資本支出或擴產，請回答『無資本支出相關資料』",
    ),
    (
        "庫存循環",
        "描述該公司的庫存情形，並在每一段敘述之後標註資料來源日期。我想更加了解該公司自身的庫存水位以及終端需求或客戶的庫存水位，接著想利用公司的接單情況來預判未來庫存循環方向",
    ),
]


# /data 選單。每項 (按鈕標籤, callback key)。key 對應 tools/uanalyze.py 的資料函式。
# 06 之後可再加 dcf 等選項。
DATA_OPTIONS: list[tuple[str, str]] = [
    ("法人共識", "consensus"),
    ("財務指標", "pershare"),
    ("供應鏈", "supply"),
    ("訂單能見度", "order"),
]



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


def _ua_menu_keyboard(symbol: str) -> InlineKeyboardMarkup:
    """Build the UAnalyze面向 selection keyboard for a symbol (3 per row)."""
    buttons = [
        InlineKeyboardButton(label, callback_data=f"ua:{symbol}:{i}")
        for i, (label, _prompt) in enumerate(UA_PROMPTS)
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    return InlineKeyboardMarkup(rows)


async def uanalyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ua <代號> — show a prompt menu; the actual analysis runs when the
    user picks an angle (see uanalyze_callback)."""
    symbol = _command_arg(update)
    if not symbol:
        await update.message.reply_text("用法：/ua <股票代號>，例 /ua 2330")
        return

    symbol = symbol.strip().upper()
    await update.message.reply_text(
        f"🧠 要看 {symbol} 的哪個面向？請選擇：",
        reply_markup=_ua_menu_keyboard(symbol),
    )


async def uanalyze_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a UAnalyze prompt-menu button press: run the chosen prompt, or
    return to the menu when the back button is pressed."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    parts = query.data.split(":", 2)
    # Back button: ua:back:<symbol> → re-show the menu.
    if len(parts) == 3 and parts[1] == "back":
        symbol = parts[2]
        await query.edit_message_text(
            f"🧠 要看 {symbol} 的哪個面向？請選擇：",
            reply_markup=_ua_menu_keyboard(symbol),
        )
        return

    try:
        _, symbol, idx_str = parts
        label, prompt = UA_PROMPTS[int(idx_str)]
    except (ValueError, IndexError):
        await query.edit_message_text("⚠️ 無效的選項")
        return

    await query.edit_message_text(f"🧠 正在分析 {symbol}（{label}）…")

    from tools.uanalyze import analyze

    try:
        r = await analyze(symbol, prompt)
    except Exception as e:
        logger.error("/ua callback failed for %s (%s): %s", symbol, label, e)
        await query.edit_message_text(f"⚠️ 分析失敗：{e}")
        return

    if "error" in r:
        await query.edit_message_text(f"😕 {r['error']}")
        return

    analysis = r.get("analysis", "")
    if isinstance(analysis, dict):
        import json as _json

        analysis = _json.dumps(analysis, ensure_ascii=False, indent=2)
    text = f"🧠 {symbol} · {label}\n{'=' * 20}\n{analysis}"
    back = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ 選其他面向", callback_data=f"ua:back:{symbol}")]]
    )
    # Telegram message hard limit is 4096 chars.
    await query.edit_message_text(text[:4096], reply_markup=back)


def _data_menu_keyboard(symbol: str) -> InlineKeyboardMarkup:
    """Build the /data option menu for a symbol (2 per row).

    callback_data format: data:{symbol}:{key} where key ∈ {consensus, pershare}.
    Structure leaves room for later tickets to append supply/order/dcf options.
    """
    buttons = [
        InlineKeyboardButton(label, callback_data=f"data:{symbol}:{key}")
        for label, key in DATA_OPTIONS
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


async def data_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /data <代號> — show a data-menu; the actual fetch runs when the
    user picks an option (see data_callback)."""
    symbol = _command_arg(update)
    if not symbol:
        await update.message.reply_text("用法：/data <股票代號>，例 /data 2330")
        return

    symbol = symbol.strip().upper()
    await update.message.reply_text(
        f"📑 要看 {symbol} 的哪類資料？請選擇：",
        reply_markup=_data_menu_keyboard(symbol),
    )


def _format_consensus(symbol: str, r: dict) -> str:
    """Condense the fetch_eps_consensus summary into readable Chinese text."""
    lines = [f"📑 {symbol} · 法人共識", "=" * 20]

    eps = r.get("eps") or {}
    if eps:
        lines.append("【單季 EPS】")
        actual = eps.get("實際EPS") or []
        if actual:
            parts = [f"{x['period']} {x['value']}" for x in actual]
            lines.append("實際：" + "、".join(parts))
        forecast = eps.get("法人共識預估EPS") or []
        if forecast:
            parts = [f"{x['period']} {x['value']}" for x in forecast]
            lines.append("法人共識預估：" + "、".join(parts))

    rev = r.get("revenue") or {}
    if rev:
        lines.append("")
        lines.append("【月營收共識（千元）】")
        est = rev.get("法人共識估計月營收") or []
        if est:
            parts = [f"{x['month']}月 {x['value']:,}" for x in est]
            lines.append("法人共識估計：" + "、".join(parts))
        ytd = rev.get("累計今年月營收") or []
        if ytd:
            parts = [f"{x['month']}月 {x['value']:,}" for x in ytd]
            lines.append("累計實際：" + "、".join(parts))
        exceed = rev.get("累計營收超法人預期(%)") or []
        if exceed:
            parts = [f"{x['month']}月 {x['value']}%" for x in exceed]
            lines.append("超法人預期：" + "、".join(parts))

    return "\n".join(lines)


def _format_pershare(symbol: str, r: dict) -> str:
    """Condense the fetch_per_share_metrics summary into readable Chinese text."""
    lines = [f"📑 {symbol} · 財務指標（近年）", "=" * 20]
    for m in r.get("metrics") or []:
        name = m.get("name", "")
        values = m.get("values") or {}
        # values dict is newest-first (D2025, D2024...).
        parts = [f"{year} {val}" for year, val in values.items()]
        lines.append(f"{name}：" + "、".join(parts))
    return "\n".join(lines)


def _format_supply(symbol: str, r: dict) -> str:
    """Condense the fetch_supply_chain summary into readable Chinese text."""
    lines = [f"📑 {symbol} · 供應鏈/同業", "=" * 20]
    peers = r.get("peers") or []
    if r.get("stock_name"):
        lines.append(f"本公司：{r['stock_name']}（{symbol}）")
    lines.append(f"同業/供應鏈標的（{len(peers)} 檔）：")
    lines.append("、".join(peers))
    return "\n".join(lines)


def _format_order(symbol: str, r: dict) -> str:
    """Condense the fetch_order_visibility summary into readable Chinese text.

    資料稀疏；兩段（訂單能見度 / 合約負債）各 best-effort，有才列。
    """
    import json as _json

    lines = [f"📑 {symbol} · 訂單能見度", "=" * 20]
    ov = r.get("order_visibility")
    if ov:
        lines.append("【訂單能見度】")
        lines.append(_json.dumps(ov, ensure_ascii=False))
    cl = r.get("contract_liability")
    if cl:
        if ov:
            lines.append("")
        lines.append("【合約負債】")
        lines.append(_json.dumps(cl, ensure_ascii=False))
    return "\n".join(lines)


async def data_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a /data menu button press: fetch the chosen data set, or return
    to the menu when the back button is pressed."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    parts = query.data.split(":", 2)
    # Back button: data:back:<symbol> → re-show the menu.
    if len(parts) == 3 and parts[1] == "back":
        symbol = parts[2]
        await query.edit_message_text(
            f"📑 要看 {symbol} 的哪類資料？請選擇：",
            reply_markup=_data_menu_keyboard(symbol),
        )
        return

    if len(parts) != 3:
        await query.edit_message_text("⚠️ 無效的選項")
        return
    _, symbol, key = parts

    labels = {k: label for label, k in DATA_OPTIONS}
    if key not in labels:
        await query.edit_message_text("⚠️ 無效的選項")
        return

    await query.edit_message_text(f"📑 正在查詢 {symbol}（{labels[key]}）…")

    from tools.uanalyze import (
        fetch_eps_consensus,
        fetch_order_visibility,
        fetch_per_share_metrics,
        fetch_supply_chain,
    )

    try:
        if key == "consensus":
            r = await fetch_eps_consensus(symbol)
        elif key == "pershare":
            r = await fetch_per_share_metrics(symbol)
        elif key == "supply":
            r = await fetch_supply_chain(symbol)
        else:
            r = await fetch_order_visibility(symbol)
    except Exception as e:
        logger.error("/data callback failed for %s (%s): %s", symbol, key, e)
        await query.edit_message_text(f"⚠️ 查詢失敗：{e}")
        return

    if "error" in r:
        await query.edit_message_text(f"😕 {r['error']}")
        return

    if key == "consensus":
        text = _format_consensus(symbol, r)
    elif key == "pershare":
        text = _format_pershare(symbol, r)
    elif key == "supply":
        text = _format_supply(symbol, r)
    else:
        text = _format_order(symbol, r)
    back = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ 選其他資料", callback_data=f"data:back:{symbol}")]]
    )
    # Telegram message hard limit is 4096 chars.
    await query.edit_message_text(text[:4096], reply_markup=back)


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
        CallbackQueryHandler(uanalyze_callback, pattern=r"^ua:"), group=0
    )
    application.add_handler(CommandHandler("data", data_command), group=0)
    application.add_handler(
        CallbackQueryHandler(data_callback, pattern=r"^data:"), group=0
    )
    application.add_handler(
        MessageHandler(filters.Entity("mention"), mention), group=0
    )
    logger.info("Handlers registered.")
