"""Telegram message handlers."""

import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from bot.reply_format import parse_reply_format
from bot.tables import code_block_capped, render_table

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
    "/ua `<代號>` — UAnalyze 估值分析＋法說會逐字稿選單，例 `/ua 2330`\n"
    "/data `<代號>` — 法人共識/財務指標/供應鏈/訂單能見度/DCF 估值選單，例 `/data 2330`\n"
    "/news — 立即抓最新新聞\n\n"
    "*問 AI（自然語言，會自動組合工具）*\n"
    "/ask `<問題>` — 例：`/ask 台積電最近怎麼樣？`（群組、私訊皆可）\n\n"
    "輸入 /help 隨時查看本說明。"
)

# UAnalyze 分析面向選單。定義已移至工具層（單一來源），這裡 re-export 供 /ua 選單使用。
# 每項為 (按鈕標籤, 實際送出的完整 prompt)。
from tools.uanalyze import UA_PROMPTS  # noqa: E402


# /data 選單。每項 (按鈕標籤, callback key)。key 對應 tools/uanalyze.py 的資料函式。
# 06 之後可再加 dcf 等選項。
DATA_OPTIONS: list[tuple[str, str]] = [
    ("法人共識", "consensus"),
    ("財務指標", "pershare"),
    ("供應鏈", "supply"),
    ("訂單能見度", "order"),
    ("DCF 估值", "dcf"),
]


# ── 法說會逐字稿分頁快取（Ticket 07，做法 2）───────────────────────────────
# 全文很長（~15K 字）。選定某場「打一次」TranscriptDetail 存進記憶體快取，之後翻頁
# 只讀快取切段落、不再打 API。快取有 TTL，過期才重抓。
import time as _time  # noqa: E402

TRANSCRIPT_PAGE_CHARS = 3500  # 每頁字數（<4096，留余裕給頁碼提示與按鈕）
TRANSCRIPT_CACHE_TTL = 600.0  # 秒；過期重抓
# {id: (fetched_at, full_text, title, date)}
_transcript_cache: dict[str, tuple[float, str, str, str]] = {}


async def _get_transcript_cached(transcript_id: str) -> dict:
    """回傳逐字稿全文 dict（快取命中且未過期→不打 API；否則打一次 API 存快取）。

    回 {'transcript','title','date'} 或 {'error': ...}。
    """
    now = _time.monotonic()
    cached = _transcript_cache.get(transcript_id)
    if cached and (now - cached[0]) < TRANSCRIPT_CACHE_TTL:
        return {"transcript": cached[1], "title": cached[2], "date": cached[3]}

    from tools.uanalyze import fetch_transcript_detail

    detail = await fetch_transcript_detail(transcript_id)
    if "error" in detail:
        return detail
    _transcript_cache[transcript_id] = (
        now,
        detail.get("transcript", ""),
        detail.get("title", ""),
        detail.get("date", ""),
    )
    return {
        "transcript": detail.get("transcript", ""),
        "title": detail.get("title", ""),
        "date": detail.get("date", ""),
    }


def _paginate(text: str, page: int) -> tuple[str, int, int]:
    """把全文切成固定長度的頁，回 (該頁內容, 目前頁碼(0-based), 總頁數)。

    page 會夾到合法範圍 [0, total-1]。空字串視為 1 頁。
    """
    total = max(1, (len(text) + TRANSCRIPT_PAGE_CHARS - 1) // TRANSCRIPT_PAGE_CHARS)
    page = max(0, min(page, total - 1))
    start = page * TRANSCRIPT_PAGE_CHARS
    chunk = text[start : start + TRANSCRIPT_PAGE_CHARS]
    return chunk, page, total



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
        from tools.draw_intraday_chart import draw as draw_intraday

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
    """Build the UAnalyze面向 selection keyboard for a symbol (3 per row).

    末列額外加一顆「法說會逐字稿」入口（tx: prefix，走獨立的分頁快取流程，
    與 ua:{symbol}:{idx} 的 AI 分析分流）。
    """
    buttons = [
        InlineKeyboardButton(label, callback_data=f"ua:{symbol}:{i}")
        for i, (label, _prompt) in enumerate(UA_PROMPTS)
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append(
        [InlineKeyboardButton("📝 法說會逐字稿", callback_data=f"tx:list:{symbol}")]
    )
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


def _transcript_page_keyboard(
    transcript_id: str, symbol: str, page: int, total: int
) -> InlineKeyboardMarkup:
    """分頁按鈕：上一頁/下一頁（第一頁無上一頁、最後頁無下一頁）+ 返回清單。

    callback_data 皆 tx:show:{id}:{page} / tx:list:{symbol}，長度遠 < 64 bytes。
    """
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton("⬅️ 上一頁", callback_data=f"tx:show:{transcript_id}:{page - 1}")
        )
    if page < total - 1:
        nav.append(
            InlineKeyboardButton("下一頁 ➡️", callback_data=f"tx:show:{transcript_id}:{page + 1}")
        )
    rows = []
    if nav:
        rows.append(nav)
    rows.append(
        [InlineKeyboardButton("📋 回逐字稿清單", callback_data=f"tx:list:{symbol}")]
    )
    return InlineKeyboardMarkup(rows)


async def transcript_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """法說會逐字稿流程（Ticket 07，做法 2 分頁快取）。

    - tx:list:{symbol} → 列該股歷次逐字稿日期清單（每場一顆按鈕 tx:show:{id}:0）。
    - tx:show:{id}:{page} → 顯示全文第 page 頁。**快取命中→不打 API**，只切段落換頁。
    """
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    parts = query.data.split(":")

    # tx:list:{symbol} → 列清單
    if len(parts) >= 3 and parts[1] == "list":
        symbol = parts[2]
        await query.edit_message_text(f"📝 正在查詢 {symbol} 的法說會逐字稿清單…")

        from tools.uanalyze import fetch_transcript_list

        try:
            r = await fetch_transcript_list(symbol)
        except Exception as e:
            logger.error("tx:list failed for %s: %s", symbol, e)
            await query.edit_message_text(f"⚠️ 查詢失敗：{e}")
            return

        if "error" in r:
            await query.edit_message_text(f"😕 {r['error']}")
            return

        transcripts = r.get("transcripts") or []
        buttons = [
            InlineKeyboardButton(
                t.get("date") or t.get("id"), callback_data=f"tx:show:{t['id']}:0"
            )
            for t in transcripts
        ]
        rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
        rows.append(
            [InlineKeyboardButton("⬅️ 選其他面向", callback_data=f"ua:back:{symbol}")]
        )
        await query.edit_message_text(
            f"📝 {symbol} 歷次法說會逐字稿（共 {len(transcripts)} 場），選一場閱讀：",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    # tx:show:{id}:{page} → 顯示某頁
    if len(parts) >= 4 and parts[1] == "show":
        transcript_id = parts[2]
        try:
            page = int(parts[3])
        except ValueError:
            page = 0

        r = await _get_transcript_cached(transcript_id)
        if "error" in r:
            await query.edit_message_text(f"😕 {r['error']}")
            return

        symbol = transcript_id[-4:]  # id = 日期 + 股號，後 4 碼為代號
        chunk, page, total = _paginate(r.get("transcript", ""), page)
        title = r.get("title", "")
        date = r.get("date", "")
        header = f"📝 {title or symbol}"
        if date:
            header += f"（{date}）"
        header += f"\n第 {page + 1}/{total} 頁\n{'=' * 20}\n"
        text = header + chunk
        keyboard = _transcript_page_keyboard(transcript_id, symbol, page, total)
        # Telegram message hard limit is 4096 chars.
        await query.edit_message_text(text[:4096], reply_markup=keyboard)
        return

    await query.edit_message_text("⚠️ 無效的選項")


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
    """Condense the fetch_eps_consensus summary into a monospace table.

    Two tables: 單季 EPS（期別 × 實際/法人預估）與 月營收共識（月 × 估計/累計/超
    預期）。Periods/months form the rows so multi-period data reads top-to-bottom
    instead of being 、-joined on one long line.
    """
    lines = [f"📑 {symbol} · 法人共識"]

    eps = r.get("eps") or {}
    if eps:
        actual = {x["period"]: x["value"] for x in (eps.get("實際EPS") or [])}
        forecast = {
            x["period"]: x["value"] for x in (eps.get("法人共識預估EPS") or [])
        }
        # Union of periods, newest-first order preserved from input.
        periods: list[str] = []
        for x in (eps.get("實際EPS") or []) + (eps.get("法人共識預估EPS") or []):
            if x["period"] not in periods:
                periods.append(x["period"])
        if periods:
            rows = [
                [p, actual.get(p, "-"), forecast.get(p, "-")] for p in periods
            ]
            lines.append("")
            lines.append("【單季 EPS】")
            lines.append(render_table(["期別", "實際", "法人預估"], rows))

    rev = r.get("revenue") or {}
    if rev:
        est = {x["month"]: x["value"] for x in (rev.get("法人共識估計月營收") or [])}
        ytd = {x["month"]: x["value"] for x in (rev.get("累計今年月營收") or [])}
        exceed = {
            x["month"]: x["value"]
            for x in (rev.get("累計營收超法人預期(%)") or [])
        }
        months: list[str] = []
        for key in (est, ytd, exceed):
            for m in key:
                if m not in months:
                    months.append(m)
        if months:
            def _fmt(v: object) -> str:
                return f"{v:,}" if isinstance(v, (int, float)) else "-"

            rows = [
                [
                    f"{m}月",
                    _fmt(est.get(m)),
                    _fmt(ytd.get(m)),
                    f"{exceed[m]}%" if m in exceed else "-",
                ]
                for m in months
            ]
            lines.append("")
            lines.append("【月營收共識（千元）】")
            lines.append(
                render_table(["月份", "法人估計", "累計實際", "超預期"], rows)
            )

    return "\n".join(lines)


def _format_pershare(symbol: str, r: dict) -> str:
    """Condense the fetch_per_share_metrics summary into a monospace table.

    Layout: metrics as rows, years as columns (指標 × 年份). Years are few
    (~5) so the table stays within a phone's width, and each metric reads
    across its recent years on one aligned row.
    """
    lines = [f"📑 {symbol} · 財務指標（近年）"]
    metrics = r.get("metrics") or []
    if not metrics:
        return "\n".join(lines)

    # Collect the union of years across all metrics, newest-first as given.
    years: list[str] = []
    for m in metrics:
        for year in (m.get("values") or {}):
            if year not in years:
                years.append(year)

    rows = []
    for m in metrics:
        values = m.get("values") or {}
        rows.append([m.get("name", "")] + [values.get(y, "-") for y in years])

    lines.append("")
    lines.append(render_table(["指標"] + years, rows))
    return "\n".join(lines)


def _format_supply(symbol: str, r: dict) -> str:
    """Condense the fetch_supply_chain summary into a monospace grid.

    Peer codes are laid out several-per-row so a long list reads as a compact
    grid instead of a single 、-joined line.
    """
    lines = [f"📑 {symbol} · 供應鏈/同業"]
    peers = r.get("peers") or []
    if r.get("stock_name"):
        lines.append(f"本公司：{r['stock_name']}（{symbol}）")
    lines.append(f"同業/供應鏈標的（{len(peers)} 檔）：")

    if peers:
        per_row = 5
        grid = [peers[i : i + per_row] for i in range(0, len(peers), per_row)]
        # No headers: render as an aligned grid of codes (all left-aligned).
        headers = [""] * per_row
        lines.append("")
        table = render_table(headers, grid, aligns=["left"] * per_row)
        # Drop the empty header + divider lines; keep only the code grid.
        body = "\n".join(table.splitlines()[2:])
        lines.append(body)
    return "\n".join(lines)


def _format_order(symbol: str, r: dict) -> str:
    """Condense the fetch_order_visibility summary into key/value tables.

    資料稀疏；兩段（訂單能見度 / 合約負債）各 best-effort，有才列。Each dict is
    rendered as a 項目 × 數值 table.
    """
    lines = [f"📑 {symbol} · 訂單能見度"]

    def _kv_table(d: dict) -> str:
        return render_table(
            ["項目", "數值"],
            [[str(k), str(v)] for k, v in d.items()],
            aligns=["left", "left"],
        )

    ov = r.get("order_visibility")
    if ov:
        lines.append("")
        lines.append("【訂單能見度】")
        lines.append(_kv_table(ov) if isinstance(ov, dict) else str(ov))
    cl = r.get("contract_liability")
    if cl:
        lines.append("")
        lines.append("【合約負債】")
        lines.append(_kv_table(cl) if isinstance(cl, dict) else str(cl))
    return "\n".join(lines)


def _format_dcf(symbol: str, r: dict) -> str:
    """Condense the fetch_dcf_valuation summary into a key/value table.

    時間加權動態 DCF（純計算，非 AI）：內在價值/前瞻價值/時間加權基期/營收動能/信心度。
    """
    lines = [f"📑 {symbol} · DCF 估值（時間加權動態）", ""]
    rows = [
        ["每股合理內在價值", f"{r.get('每股合理內在價值')} 元"],
        ["1年後前瞻合理價值", f"{r.get('1年後前瞻合理價值')} 元"],
        ["當前時間加權基期", f"{r.get('當前時間加權基期')} 元"],
        ["營收動能", str(r.get("營收動能"))],
        ["2025 實際獲利", str(r.get("2025實際獲利"))],
        ["2026E", str(r.get("2026E"))],
        ["最遠預估", str(r.get("最遠預估年份及獲利"))],
        ["信心度", str(r.get("信心度"))],
    ]
    lines.append(render_table(["項目", "數值"], rows, aligns=["left", "left"]))
    lines.append("")
    lines.append("＊純數學估值（WACC/時間加權/成長衰減），非 AI；僅供參考。")
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
        fetch_dcf_valuation,
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
        elif key == "dcf":
            r = await fetch_dcf_valuation(symbol)
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
    elif key == "dcf":
        text = _format_dcf(symbol, r)
    else:
        text = _format_order(symbol, r)
    back = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ 選其他資料", callback_data=f"data:back:{symbol}")]]
    )
    # Wrap in a fenced code block so Telegram renders the tables in a monospace
    # font (space-aligned columns only line up in monospace). Sent with legacy
    # Markdown parse_mode; inside a fence only backticks are special, so the
    # CJK/number content is safe. `code_block_capped` fences first, then caps to
    # Telegram's 4096-char limit measured on the *final* string, so the fence
    # markers and any inside-fence escaping can't push it over the edge.
    await query.edit_message_text(
        code_block_capped(text), reply_markup=back, parse_mode="Markdown"
    )


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

        prompt = build_mention_prompt(text_after)
        result = await bridge.send_detailed(prompt)

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
        tools_line = result.tools_line() if _show_agent_tools() else ""
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
    application.add_handler(CommandHandler("ua", uanalyze_command), group=0)
    application.add_handler(
        CallbackQueryHandler(uanalyze_callback, pattern=r"^ua:"), group=0
    )
    application.add_handler(
        CallbackQueryHandler(transcript_callback, pattern=r"^tx:"), group=0
    )
    application.add_handler(CommandHandler("data", data_command), group=0)
    application.add_handler(
        CallbackQueryHandler(data_callback, pattern=r"^data:"), group=0
    )
    application.add_handler(CommandHandler("ask", ask_command), group=0)
    logger.info("Handlers registered.")
