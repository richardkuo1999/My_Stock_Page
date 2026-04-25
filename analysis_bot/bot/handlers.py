import asyncio
import io
import json
import logging
import os
import re
from contextlib import suppress
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from docx import Document as DocxDocument
from sqlmodel import Session, select

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from ..config import get_settings
from ..database import engine
from ..models.intraday_ma import IntradayMA20Snapshot
from ..models.subscriber import Subscriber
from ..models.stock import StockData
from ..models.threads_watch import ThreadsWatchEntry
from ..models.watchlist import WatchlistEntry
from ..services.ai_service import AIService, RequestType
from ..services.blake_chips_scraper import fetch_chips_data, fetch_chips_data_888
from ..services.intraday_chart import render_intraday_chart
from ..services.intraday_spike_scanner import IntradaySpikeScanner
from ..services.legacy_scraper import LegacyMoneyDJ
from ..services.uanalyze_ai import analyze_stock as uanalyze_analyze
from ..services.news_parser import NewsParser
from ..services.price_fetcher import fetch_price
from ..services.report_generator import ReportGenerator
from ..services.spike_pager import (
    build_spike_markdown_header,
    build_spike_telegram_html_messages,
)
from ..services.stock_service import StockService
from ..services.vix_fetcher import fetch_vix_snapshot, format_vix_message
from ..services.volume_spike_scanner import SpikeSortBy, VolumeSpikeScanner
from .jobs import process_threads_watch_entry

logger = logging.getLogger(__name__)

# Constants
MAX_ALIAS_LENGTH = 64
_THREADS_USERNAME_RE = re.compile(r"^[A-Za-z0-9._]+$")

# Conversation states
ASK_RESEARCH = 1
ASK_CHAT = 5


def _build_news_main_keyboard():
    """共用的新聞來源選單 InlineKeyboard。"""
    return [
        [
            InlineKeyboardButton("鉅亨網 (CNYES)", callback_data="news_cnyes"),
            InlineKeyboardButton("Google News (TW)", callback_data="news_google"),
        ],
        [
            InlineKeyboardButton("Moneydj", callback_data="news_moneydj"),
            InlineKeyboardButton("Yahoo 股市", callback_data="news_yahoo"),
        ],
        [
            InlineKeyboardButton("聯合新聞網 (UDN)", callback_data="news_udn"),
            InlineKeyboardButton("UAnalyze", callback_data="news_uanalyze"),
        ],
        [
            InlineKeyboardButton("財經M平方", callback_data="news_macromicro"),
            InlineKeyboardButton("瑞星財經 (FinGuider)", callback_data="news_finguider"),
        ],
        [
            InlineKeyboardButton("Fintastic", callback_data="news_fintastic"),
            InlineKeyboardButton("Forecastock", callback_data="news_forecastock"),
        ],
        [
            InlineKeyboardButton("方格子 (Vocus)", callback_data="news_vocus_menu"),
            InlineKeyboardButton("NewsDigest AI", callback_data="news_ndai"),
        ],
        [InlineKeyboardButton("Fugle Report", callback_data="news_fugle")],
        [
            InlineKeyboardButton("永豐｜3分鐘產業百科", callback_data="news_sinotrade_industry"),
            InlineKeyboardButton("口袋學堂｜研究報告", callback_data="news_pocket_report"),
        ],
    ]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "Stock Analysis Bot Ready!\n輸入 /help 查看所有指令"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display help categories with inline keyboard."""
    rows = []
    for i in range(0, len(_HELP_CATEGORIES), 2):
        row = [InlineKeyboardButton(t, callback_data=d) for t, d in _HELP_CATEGORIES[i:i + 2]]
        rows.append(row)
    await update.message.reply_text(
        "📖 *指令說明 — 選擇分類：*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


_HELP_CATEGORIES = [
    ("🏠 基本", "help_basic"),
    ("📊 資訊查詢", "help_query"),
    ("🔥 爆量偵測", "help_spike"),
    ("📰 新聞搜尋", "help_news"),
    ("🤖 AI 工具", "help_ai"),
    ("⭐ 自選股", "help_watch"),
    ("🏦 持股查詢", "help_hold"),
    ("📬 訂閱管理", "help_sub"),
    ("🔬 UAnalyze", "help_ua"),
    ("⚙️ 其他", "help_misc"),
]

_HELP_PAGES = {
    "help_basic": (
        "🏠 *基本*\n\n"
        "• `/start` — 啟動機器人\n"
        "• `/help` — 指令分類選單\n"
        "• `/menu` — 互動式操作選單"
    ),
    "help_query": (
        "📊 *資訊查詢*\n\n"
        "• `/p <股號>` — 💹 即時股價 + 走勢圖\n"
        "• `/k <股號>` — 📈 K 線圖（近 3 個月）\n"
        "  參數：`rsi` `macd` `kd` `bb` `dmi` + 自訂 MA\n"
        "  例：`/k 2330 bb kd`\n"
        "• `/info <股號>` — 🏢 基本面 AI 報告\n"
        "• `/esti <股號>` — 🎯 樂活五線譜估值\n"
        "• `/name <股號>` — 🏷 查詢公司名稱\n"
        "• `/vix` — 😱 VIX 恐慌指數"
    ),
    "help_spike": (
        "🔥 *爆量偵測*\n\n"
        "• `/spike` — 收盤爆量（按倍數）\n"
        "• `/spike change` — 按漲幅排序\n"
        "• `/spike t1` — 按前日倍數\n"
        "• `/ispike` — ⚡ 盤中爆量\n"
        "• `/ispike change` — 盤中按漲幅\n"
        "• `/sub_ispike` — 🔔 訂閱通知\n"
        "• `/unsub_ispike` — 🔕 取消通知"
    ),
    "help_news": (
        "📰 *新聞與搜尋*\n\n"
        "• `/news` — 新聞來源選單\n"
        "• `/google <關鍵字>` — 🔍 Google 新聞\n"
        "  例：`/google 台積電`\n"
        "• `/senti <股號>` — 📊 個股情緒趨勢（7 天）\n"
        "• `/senti market` — 📊 市場情緒摘要"
    ),
    "help_ai": (
        "🤖 *AI 工具*\n\n"
        "• `/chat <問題>` — 💬 單次回答\n"
        "• `/chat` — 對話模式（exit 離開）\n"
        "• `/research` — 📚 上傳文件生成摘要\n"
        "  上傳後輸入 `/rq` 產生報告"
    ),
    "help_watch": (
        "⭐ *自選股 & 追蹤*\n\n"
        "• `/wadd <股號> [備註]` — 加入自選股\n"
        "• `/wdel <股號>` — 移除自選股\n"
        "• `/wlist` — 查看清單\n"
        "• `/threads add <帳號>` — 🧵 訂閱 Threads\n"
        "• `/threads remove <帳號>` — 取消訂閱\n"
        "• `/threads list` — 訂閱清單\n"
        "• `/threads check` — 檢查新貼文"
    ),
    "help_hold": (
        "🏦 *持股查詢*\n\n"
        "• `/hold981` — 00981A 持股變化\n"
        "• `/hold981 2026-03-18` — 指定日期\n"
        "• `/hold888` — 大額權證買超"
    ),
    "help_sub": (
        "📬 *訂閱管理*\n\n"
        "• `/sub_news` — 📰 訂閱新聞推播\n"
        "• `/unsub_news` — 取消新聞推播\n"
        "• `/sub_senti` — 🔔 訂閱情緒警報\n"
        "• `/unsub_senti` — 取消情緒警報\n"
        "• `/sub_daily` — 📊 訂閱每日分析\n"
        "• `/unsub_daily` — 取消每日分析\n"
        "• `/sub_spike` — 💥 訂閱收盤爆量\n"
        "• `/unsub_spike` — 取消收盤爆量\n"
        "• `/sub_vix` — ⚡ 訂閱 VIX 警報\n"
        "• `/unsub_vix` — 取消 VIX 警報"
    ),
    "help_ua": (
        "🔬 *UAnalyze / MEGA*\n\n"
        "• `/ua <股號>` — AI 多題分析\n"
        "• `/uask <股號> <問題>` — 自訂問題\n"
        "• `/umon` — 觸發報告檢查\n"
        "• `/sub_umon` — 訂閱推播\n"
        "• `/unsub_umon` — 取消推播\n"
        "• `/mega y|n <關鍵字>` — MEGA 搜尋下載"
    ),
    "help_misc": (
        "⚙️ *其他*\n\n"
        "• `/chatid` — 查看 Chat ID\n"
        "• `/menu` — 互動式指令選單"
    ),
}


async def help_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle help category button presses."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "help_back":
        rows = []
        for i in range(0, len(_HELP_CATEGORIES), 2):
            row = [InlineKeyboardButton(t, callback_data=d) for t, d in _HELP_CATEGORIES[i:i + 2]]
            rows.append(row)
        await query.edit_message_text(
            "📖 *指令說明 — 選擇分類：*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if data in _HELP_PAGES:
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回分類", callback_data="help_back")]])
        await query.edit_message_text(
            _HELP_PAGES[data],
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_kb,
        )


# --- Menu (InlineKeyboard) ---

_MENU_CATEGORIES = [
    ("📊 資訊查詢", "menu_cat_query"),
    ("🔥 爆量偵測", "menu_cat_spike"),
    ("📰 新聞與搜尋", "menu_cat_news"),
    ("🤖 AI 工具", "menu_cat_ai"),
    ("🔬 UAnalyze", "menu_cat_ua"),
    ("⭐ 自選股 & 追蹤", "menu_cat_watch"),
    ("🏦 持股查詢", "menu_cat_hold"),
    ("📬 訂閱管理", "menu_cat_sub"),
    ("⚙️ 其他", "menu_cat_misc"),
]

# Each category: (description_text, buttons)
# Buttons: list of rows, each row is list of (label, action)
# action: str starting with "/" → switch_inline_query_current_chat (insert to input)
#          str starting with "!" → callback_data to execute directly
_MENU_PAGES: dict[str, tuple[str, list[list[tuple[str, str]]]]] = {
    "menu_cat_query": (
        "📊 *資訊查詢*\n點擊按鈕將指令填入輸入框，補上股號後送出",
        [
            [("💹 股價 /p", "/p "), ("📈 K線 /k", "/k ")],
            [("🏢 介紹 /info", "/info "), ("🎯 估值 /esti", "/esti ")],
            [("🏷 名稱 /name", "/name "), ("😱 VIX", "!vix")],
        ],
    ),
    "menu_cat_spike": (
        "🔥 *爆量偵測*\n點擊直接執行",
        [
            [("🔥 收盤爆量", "!spike"), ("🔥 按漲幅", "!spike_change")],
            [("⚡ 盤中爆量", "!ispike"), ("⚡ 按漲幅", "!ispike_change")],
            [("🔔 訂閱通知", "!sub_ispike"), ("🔕 取消通知", "!unsub_ispike")],
        ],
    ),
    "menu_cat_news": (
        "📰 *新聞與搜尋*",
        [
            [("📰 新聞選單", "!news")],
            [("🔍 Google 新聞", "/google ")],
        ],
    ),
    "menu_cat_ai": (
        "🤖 *AI 工具*",
        [
            [("💬 AI 聊天", "/chat "), ("💬 對話模式", "!chat_mode")],
            [("📚 上傳研究", "!research")],
        ],
    ),
    "menu_cat_ua": (
        "🔬 *UAnalyze / MEGA*",
        [
            [("🔬 AI 分析 /ua", "/ua "), ("💡 自訂問題 /uask", "/uask ")],
            [("📥 MEGA 拉取", "/mega y "), ("📥 MEGA 暫存", "/mega n ")],
        ],
    ),
    "menu_cat_watch": (
        "⭐ *自選股 & 追蹤*\n點擊按鈕將指令填入輸入框",
        [
            [("➕ 加入", "/wadd "), ("➖ 移除", "/wdel ")],
            [("📋 清單", "!wlist")],
            [("🧵 追蹤 Threads", "/threads add "), ("🧵 清單", "!threads_list")],
        ],
    ),
    "menu_cat_hold": (
        "🏦 *持股查詢*\n點擊直接執行（或填入日期）",
        [
            [("00981A 持股", "!hold981"), ("指定日期", "/hold981 ")],
            [("大額權證", "!hold888")],
        ],
    ),
    "menu_cat_sub": (
        "📬 *訂閱管理*",
        [
            [("✅ 訂閱推播", "!subscribe"), ("❌ 取消訂閱", "!unsubscribe")],
        ],
    ),
    "menu_cat_misc": (
        "⚙️ *其他*",
        [
            [("🆔 Chat ID", "!chatid"), ("📖 完整指令", "!help")],
        ],
    ),
}


def _build_menu_main_keyboard():
    rows = []
    for i in range(0, len(_MENU_CATEGORIES), 2):
        row = [InlineKeyboardButton(t, callback_data=d) for t, d in _MENU_CATEGORIES[i:i + 2]]
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _build_category_keyboard(page_buttons: list[list[tuple[str, str]]]):
    """Build keyboard for a category page. All buttons execute directly."""
    rows = []
    for row_def in page_buttons:
        row = []
        for label, action in row_def:
            if action.startswith("/"):
                # Convert "/" actions to "!" callback format
                row.append(InlineKeyboardButton(label, callback_data=f"menu_exec!{action.strip()}"))
            else:
                row.append(InlineKeyboardButton(label, callback_data=f"menu_exec{action}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 返回選單", callback_data="menu_back")])
    return InlineKeyboardMarkup(rows)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show interactive menu with inline keyboard."""
    await update.message.reply_text(
        "📋 *選擇分類：*", parse_mode=ParseMode.MARKDOWN,
        reply_markup=_build_menu_main_keyboard(),
    )


async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu category and execution button presses."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_back":
        await query.edit_message_text(
            "📋 *選擇分類：*", parse_mode=ParseMode.MARKDOWN,
            reply_markup=_build_menu_main_keyboard(),
        )
        return

    # Category page
    if data in _MENU_PAGES:
        text, buttons = _MENU_PAGES[data]
        await query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=_build_category_keyboard(buttons),
        )
        return

    # Direct execution: menu_exec!command
    if data.startswith("menu_exec!"):
        cmd = data[len("menu_exec!"):]

        # Handle "/cmd " format (needs args) — reply with usage hint
        if cmd.startswith("/"):
            parts = cmd.strip().lstrip("/").split()
            cmd_name = parts[0]
            hint = f"請輸入：/{' '.join(parts)} <股號>"
            await query.message.reply_text(hint)
            return

        # Map to handler functions
        _CMD_MAP = {
            "vix": vix_command,
            "spike": spike_command,
            "spike_change": lambda u, c: spike_command(u, _fake_context(c, ["change"])),
            "ispike": intraday_spike_command,
            "ispike_change": lambda u, c: intraday_spike_command(u, _fake_context(c, ["change"])),
            "sub_ispike": sub_ispike_command,
            "unsub_ispike": unsub_ispike_command,
            "news": news_command,
            "google": lambda u, c: query.message.reply_text("請輸入：/google <關鍵字>"),
            "chat_mode": chat_start,
            "research": research_start,
            "wlist": wlist_command,
            "threads_list": lambda u, c: threads_command(u, _fake_context(c, ["list"])),
            "hold981": hold981_command,
            "hold888": hold888_command,
            "subscribe": sub_news_command,
            "unsubscribe": unsub_news_command,
            "chatid": chatid_command,
            "help": help_command,
            "ua": lambda u, c: query.message.reply_text("請輸入：/ua <股號>"),
            "uask": lambda u, c: query.message.reply_text("請輸入：/uask <股號> <問題>"),
            "mega_y": lambda u, c: query.message.reply_text("請輸入：/mega y <關鍵字>"),
            "mega_n": lambda u, c: query.message.reply_text("請輸入：/mega n <關鍵字>"),
            "umon": umon_command,
        }
        handler = _CMD_MAP.get(cmd)
        if handler:
            # Create a fake Update with message from callback_query
            fake_update = Update(
                update_id=update.update_id,
                message=query.message,
            )
            # Patch effective_chat and effective_user
            fake_update._effective_chat = update.effective_chat
            fake_update._effective_user = update.effective_user
            await handler(fake_update, context)


class _fake_context:
    """Minimal context wrapper to inject args into command handlers called from menu."""

    def __init__(self, real_context, args):
        self._ctx = real_context
        self.args = args

    def __getattr__(self, name):
        return getattr(self._ctx, name)


# --- Core Logic Functions (Reusable) ---

# UAnalyze prompts subset for /info (keep it fast)
_INFO_UA_PROMPTS = ["公司概覽", "近況發展", "❤️產品線分析", "利多因素", "利空因素", "長短期展望"]


async def run_info_analysis(update: Update, ticker: str):
    await update.message.reply_text(f"✅ 你輸入的股號是 {ticker}，幫你處理！📊")

    dj = LegacyMoneyDJ()
    try:
        # 1. Parallel fetch: MoneyDJ wiki + UAnalyze AI
        wiki_task = dj.get_wiki_result(ticker)
        ua_task = uanalyze_analyze(ticker, prompts=_INFO_UA_PROMPTS)

        wiki_result, ua_md = await asyncio.gather(
            wiki_task, ua_task, return_exceptions=True,
        )

        # Handle wiki failure
        if isinstance(wiki_result, BaseException):
            logger.warning(f"MoneyDJ failed for {ticker}: {wiki_result}")
            stock_name, wiki_text = None, None
        else:
            stock_name, wiki_text = wiki_result
        if not stock_name:
            await update.message.reply_text(f"❌ 找不到 {ticker} 的相關資訊。")
            return

        # Handle UAnalyze failure gracefully
        if isinstance(ua_md, BaseException):
            logger.warning(f"UAnalyze failed for {ticker}: {ua_md}")
            ua_md = ""

        # 2. Combine sources for AI
        combined = ""
        if wiki_text:
            combined += f"=== MoneyDJ 百科 ===\n{wiki_text}\n\n"
        if ua_md:
            combined += f"=== UAnalyze AI 分析 ===\n{ua_md}\n\n"

        ai = AIService()
        condition = (
            "根據以下資料，整理近1年的公司產品、營收占比、業務來源、"
            "財務狀況(營收、eps、毛利率等)、近況發展、利多與利空因素、"
            "長短期展望，加上 google 搜尋結果，要幫我標示來源"
        )
        prompt = "\n" + condition + "，並且使用繁體中文回答\n"

        # 3. Call AI
        await update.message.reply_chat_action(ChatAction.TYPING)
        response = await ai.call(RequestType.TEXT, contents=combined, prompt=prompt)

        if response:
            file_name = f"{ticker}{stock_name}_info.md"
            f = io.BytesIO(response.encode("utf-8"))
            f.name = file_name
            await update.message.reply_document(
                document=InputFile(f, filename=file_name),
                caption="這是你的報告(含UAnalyze+google搜尋) 📄",
            )
        else:
            await update.message.reply_text("抱歉我壞了 (AI Error)")

    except Exception as e:
        logger.error(f"Error in info_analysis: {e}")
        await update.message.reply_text("❌ 分析過程發生錯誤，請稍後再試。")


async def run_esti_analysis(update: Update, ticker: str):
    await update.message.reply_text(f"⏳ 估值分析中：{ticker}")
    # StockAnalyzer not needed here, analysis goes through AIService
    try:
        await update.message.reply_chat_action(ChatAction.TYPING)

        # Use Shared Service
        data, from_cache = await StockService.get_or_analyze_stock(ticker)

        if from_cache:
            # Optional: We could get timestamp from data if stored, or just generic message
            await update.message.reply_text("♻️ Using cached data")

        if not data or "error" in data:
            error_msg = data.get("error", "Unknown error") if data else "Unknown error"
            await update.message.reply_text(f"❌ 錯誤：{error_msg}")
            return

        # Use ReportGenerator with Telegram format
        report_text = ReportGenerator.generate_telegram_report(data)

        file_name = f"{ticker}_est.md"
        f = io.BytesIO(report_text.encode("utf-8"))
        f.name = file_name

        await update.message.reply_document(
            document=InputFile(f, filename=file_name), caption="這是你的報告📄"
        )

    except Exception as e:
        logger.error(f"Error in esti_analysis: {e}")
        await update.message.reply_text("❌ 估值分析過程發生錯誤，請稍後再試。")


# --- Command Handlers ---
async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get stock information using Legacy MoneyDJ + AI."""
    if not context.args:
        await update.message.reply_text("❌ 用法：/info <股票股號>\n例如：/info 2330")
        return
    await run_info_analysis(update, context.args[0])


async def esti_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get estimation/valuation analysis."""
    if not context.args:
        await update.message.reply_text("❌ 用法：/esti <股票股號>\n例如：/esti 2330")
        return
    await run_esti_analysis(update, context.args[0])


# --- Chat ---
async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """One-off chat or enter persistent chat mode when no args."""
    if not context.args:
        return await chat_start(update, context)

    user_msg = " ".join(context.args)
    ai = AIService()
    await update.message.reply_chat_action(ChatAction.TYPING)
    try:
        resp = await ai.call(
            RequestType.TEXT, contents=user_msg, use_search=True
        )
        await update.message.reply_text(resp)
    except Exception as e:
        await update.message.reply_text(f"❌ AI 回應失敗：{e}")


def _parse_hold_date(context) -> str | None:
    """解析日期參數，回傳 None 表示用今天。"""
    date_str = context.args[0].strip() if context.args else None
    if date_str:
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return "invalid"
    return date_str


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """即時股價查詢。用法：/p 2330"""
    logger.info("price_command received: args=%s", context.args)
    ticker = context.args[0].strip() if context.args and context.args[0] else None
    if not ticker:
        await update.message.reply_text("❌ 用法：/p 2330")
        return
    await update.message.reply_chat_action(ChatAction.TYPING)
    try:
        text = await fetch_price(ticker)
        # Extract name from price text: "📈2330 台積電\n💰..."
        ticker_upper = ticker.strip().upper()
        name = ticker_upper
        first_line = text.split("\n")[0] if text else ""
        if ticker_upper in first_line:
            after = first_line.split(ticker_upper, 1)[-1].strip()
            if after:
                name = after
        # Telegram callback_data max 64 bytes; truncate name
        cb_name = name[:20]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📰 相關新聞", callback_data=f"pnews:{ticker_upper}:{cb_name}")]
        ])
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    except Exception as e:
        logger.exception("Price command error")
        await update.message.reply_text(f"❌ 查詢失敗：{str(e)[:150]}")
        return

    try:
        chart_path = await render_intraday_chart(ticker)
        if chart_path:
            try:
                with open(chart_path, "rb") as f:
                    await update.message.reply_photo(photo=f)
            finally:
                with suppress(OSError):
                    os.remove(chart_path)
    except Exception as e:
        logger.debug("intraday chart send failed: %s", e)


async def price_news_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 📰 相關新聞 button click from /p command."""
    query = update.callback_query
    await query.answer()
    # callback_data format: "pnews:{ticker}:{name}"
    parts = query.data.split(":", 2)
    if len(parts) < 2:
        return
    ticker = parts[1]
    name = parts[2] if len(parts) > 2 else ticker
    try:
        from ..services.price_fetcher import _format_news_section
        from ..services.stock_news_fetcher import fetch_stock_news
        from ..utils.ticker_utils import is_taiwan_ticker

        is_tw = is_taiwan_ticker(ticker)
        news_list = await fetch_stock_news(ticker, name, limit=5, is_tw=is_tw)
        news_text = _format_news_section(news_list)
        if news_text:
            await query.message.reply_text(news_text.strip(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        else:
            await query.message.reply_text(f"📰 {ticker} 暫無相關新聞")
    except Exception as e:
        logger.debug("price news callback error: %s", e)
        await query.message.reply_text(f"❌ 新聞查詢失敗：{str(e)[:150]}")


async def kline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """日 K 線圖（近 3 個月）。

    用法：
      /k 2330              → 預設 MA5/20/60
      /k 2330 5 10 20      → 自訂 MA 週期
      /k 2330 rsi          → 加入 RSI(14)
      /k 2330 macd         → 加入 MACD(12,26,9)
      /k 2330 kd           → 加入 KD(9,3,3)
      /k 2330 bb           → 加入布林通道
      /k 2330 dmi          → 加入 DMI(14)
      /k 2330 5 10 20 rsi macd kd bb dmi → 全部自訂
    """
    logger.info("kline_command received: args=%s", context.args)
    if not context.args:
        await update.message.reply_text(
            "❌ 用法：/k 2330 [MA週期...] [rsi] [macd] [kd] [bb] [dmi]\n"
            "範例：\n"
            "  /k 2330\n"
            "  /k 2330 5 10 20\n"
            "  /k 2330 rsi macd\n"
            "  /k 2330 kd bb dmi\n"
            "  /k 2330 bb        ← 布林通道（不含 MA）\n"
            "  /k 2330 10 20 rsi kd bb"
        )
        return

    ticker = context.args[0].strip()
    # 解析後續參數：數字 = MA 週期，rsi/macd/kd/bb/dmi = 指標開關
    ma_periods = []
    show_rsi = False
    show_macd = False
    show_kd = False
    show_bb = False
    show_dmi = False

    for arg in context.args[1:]:
        arg_lower = arg.strip().lower()
        if arg_lower == "rsi":
            show_rsi = True
        elif arg_lower == "macd":
            show_macd = True
        elif arg_lower == "kd":
            show_kd = True
        elif arg_lower == "bb":
            show_bb = True
        elif arg_lower == "dmi":
            show_dmi = True
        elif arg_lower.isdigit():
            period = int(arg_lower)
            if 2 <= period <= 240:
                ma_periods.append(period)
        # 忽略無法辨識的參數

    # 限制最多 6 條 MA 線
    if len(ma_periods) > 6:
        ma_periods = ma_periods[:6]

    # 沒指定就用預設值
    if not ma_periods:
        ma_periods = [] if show_bb else None  # BB 開啟時不疊加預設 MA

    await update.message.reply_chat_action(ChatAction.TYPING)
    try:
        # Lazy import: candlestick_chart depends on playwright
        from ..services.candlestick_chart import render_candlestick_chart

        chart_path = await render_candlestick_chart(
            ticker,
            ma_periods=ma_periods,
            show_rsi=show_rsi,
            show_macd=show_macd,
            show_kd=show_kd,
            show_bb=show_bb,
            show_dmi=show_dmi,
        )
        if not chart_path:
            await update.message.reply_text(f"❌ 找不到 {ticker} 的 K 線資料")
            return
        try:
            with open(chart_path, "rb") as f:
                await update.message.reply_photo(photo=f)
        finally:
            with suppress(OSError):
                os.remove(chart_path)
    except Exception as e:
        logger.exception("kline command error")
        await update.message.reply_text(f"❌ K 線產生失敗：{str(e)[:150]}")


async def hold981_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """00981A 持股變化。用法：/hold981 或 /hold981 2026-03-18"""
    date_str = _parse_hold_date(context)
    if date_str == "invalid":
        await update.message.reply_text("❌ 日期格式錯誤，請用 YYYY-MM-DD，例如：2026-03-18")
        return

    await update.message.reply_chat_action(ChatAction.TYPING)
    try:
        text = await fetch_chips_data(date_str=date_str)
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"hold981 error: {e}")
        await update.message.reply_text(f"❌ 取得 00981A 持股變化失敗：{str(e)[:200]}")


async def hold888_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """00981A 大額權證買超。用法：/hold888 或 /hold888 2026-03-18"""
    date_str = _parse_hold_date(context)
    if date_str == "invalid":
        await update.message.reply_text("❌ 日期格式錯誤，請用 YYYY-MM-DD，例如：2026-03-18")
        return

    await update.message.reply_chat_action(ChatAction.TYPING)
    try:
        text = await fetch_chips_data_888(date_str=date_str)
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"hold888 error: {e}")
        await update.message.reply_text(f"❌ 取得大額權證買超失敗：{str(e)[:200]}")


async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """回傳目前 chat 的 ID，方便設定通知目標。"""
    chat = update.effective_chat
    lines = [f"Chat ID: {chat.id}"]
    if getattr(update.message, "message_thread_id", None):
        lines.append(f"Topic (thread) ID: {update.message.message_thread_id}")
    lines.append(f"Chat type: {chat.type}")
    if chat.title:
        lines.append(f"Chat name: {chat.title}")
    await update.message.reply_text("\n".join(lines))


async def vix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """手動查詢 VIX 恐慌指數現值。"""
    await update.message.reply_text("📊 查詢 VIX 中...")
    try:
        snap = await fetch_vix_snapshot()
        if snap is None:
            await update.message.reply_text("❌ 無法取得 VIX 資料，請稍後再試。")
            return
        await update.message.reply_text(format_vix_message(snap))
    except Exception as e:
        await update.message.reply_text(f"❌ VIX 查詢失敗：{e}")


async def spike_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    手動觸發爆量偵測：掃描台灣上市櫃股票，找出成交量異常放大的個股。

    用法：
        /spike          # 預設按倍數排序
        /spike change   # 按漲幅排序
    """
    # 解析排序參數
    sort_arg = context.args[0] if context.args else SpikeSortBy.RATIO.value
    try:
        sort_by = SpikeSortBy(sort_arg)
    except ValueError:
        await update.message.reply_text(
            "❌ 無效的排序選項。可用選項：\n"
            "• ratio - 按爆量倍數降序（預設）\n"
            "• change - 按漲幅降序\n"
            "• t1 - 按前日倍數降序"
        )
        return

    await update.message.reply_text(
        f"🔥 正在掃描爆量股（排序：{sort_by.display_name}）...（約 1–2 分鐘）"
    )
    await update.message.reply_chat_action(ChatAction.TYPING)

    try:
        scanner = VolumeSpikeScanner()
        spike_scan = await scanner.scan(sort_by=sort_by)
        results = spike_scan.results

        if not results:
            await update.message.reply_text(
                "📊 無符合條件之爆量股（倍數 ≥ 1.5x）\n\n"
                f"📅 {spike_scan.data_date_caption}"
            )
            return

        header = build_spike_markdown_header(len(results), sort_by=sort_by)
        spike_msgs = build_spike_telegram_html_messages(results, header)
        for i, msg in enumerate(spike_msgs):
            if i > 0:
                await asyncio.sleep(0.5)
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

        if get_settings().SPIKE_NEWS_ENRICHMENT_ENABLED:
            await update.message.reply_text("📰 正在擷取爆量第 1 檔的題材與產業消息（試跑）…")
            try:
                results = await asyncio.wait_for(
                    scanner.enrich_with_news(results, top_n=1, max_news_per_stock=5),
                    timeout=60,
                )
                r = results[0]
                if r.analysis and r.analysis != "近期無相關新聞":
                    detail = f"📈 *{r.name}*（{r.ticker}）{r.spike_ratio:.1f}x\n{r.analysis}"
                    if r.news_titles:
                        detail += "\n\n_相關新聞：_ " + "；".join(r.news_titles[:3])
                    await update.message.reply_text(detail, parse_mode=ParseMode.MARKDOWN)
            except asyncio.TimeoutError:
                logger.warning("Spike news enrichment timed out (60s)")
                await update.message.reply_text("⚠️ 題材分析逾時，請稍後再試。")
            except Exception as enrich_err:
                logger.warning("Spike news enrichment failed: %s", enrich_err)
                await update.message.reply_text("⚠️ 題材分析暫時無法使用，請稍後再試。")

    except Exception as e:
        logger.error(f"Spike command error: {e}")
        await update.message.reply_text(f"❌ 爆量偵測失敗：{str(e)[:200]}")


async def intraday_spike_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    手動觸發盤中爆量偵測，使用前日 MA20 快照比對當前成交量。

    用法：
        /ispike          # 用現有快照掃描
        /ispike change   # 按漲幅排序
    """
    # 解析排序參數
    sort_arg = (context.args[0] if context.args else SpikeSortBy.RATIO.value)
    try:
        sort_by = SpikeSortBy(sort_arg)
    except ValueError:
        await update.message.reply_text(
            "❌ 無效的排序選項。可用選項：\n"
            "• ratio - 按爆量倍數降序（預設）\n"
            "• change - 按漲幅降序\n"
            "• t1 - 按前日倍數降序"
        )
        return

    # 載入 MA20 快照
    def _load():
        with Session(engine) as session:
            rows = session.exec(select(IntradayMA20Snapshot)).all()
            return {r.ticker: {"name": r.name, "market": r.market, "ma20_lots": r.ma20_lots, "vol_19d_sum_lots": r.vol_19d_sum_lots}
                    for r in rows}

    try:
        ma20_snapshot = await asyncio.to_thread(_load)
    except Exception as e:
        logger.error("ispike _load snapshot failed: %s", e)
        await update.message.reply_text(f"❌ 讀取快照失敗：{str(e)[:200]}")
        return

    if not ma20_snapshot:
        await update.message.reply_text(
            "⚠️ MA20 快照尚未建立。\n"
            "請先等待每日 15:30 的收盤爆量掃描完成後再使用，\n"
            "或執行 /spike 手動觸發收盤掃描。"
        )
        return

    await update.message.reply_text(
        f"🔥 盤中爆量掃描中（排序：{sort_by.display_name}）...（約 5-15 秒）"
    )
    await update.message.reply_chat_action(ChatAction.TYPING)

    try:
        settings = get_settings()

        scanner = IntradaySpikeScanner()
        results = await scanner.scan_intraday(
            ma20_snapshot=ma20_snapshot,
            base_spike_ratio=settings.INTRADAY_SPIKE_BASE_RATIO,
            min_lots=settings.INTRADAY_SPIKE_MIN_LOTS,
            sort_by=sort_by,
        )

        if not results:
            now = datetime.now(ZoneInfo("Asia/Taipei"))
            elapsed = scanner.get_elapsed_minutes()
            if elapsed < 30:
                msg = f"⏳ 開盤尚未滿 30 分鐘（{elapsed} 分鐘），等待訊號穩定"
            else:
                msg = f"📊 無盤中爆量股（快照 {len(ma20_snapshot)} 支，目前未達閾值）"
            await update.message.reply_text(msg)
            return

        header = "[盤中] " + build_spike_markdown_header(len(results), sort_by=sort_by)
        spike_msgs = build_spike_telegram_html_messages(results, header)
        for i, msg in enumerate(spike_msgs):
            if i > 0:
                await asyncio.sleep(0.5)
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Intraday spike command error: {e}")
        await update.message.reply_text(f"❌ 盤中爆量偵測失敗：{str(e)[:200]}")


async def chat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enter persistent chat mode."""
    await update.message.reply_text(
        "💬 進入 AI 聊天模式！\n你可以直接跟我對話，輸入 'exit' 或 'cancel' 離開。"
    )
    return ASK_CHAT


async def chat_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle persistent chat messages."""
    user_msg = update.message.text
    if user_msg.lower() in ["exit", "cancel"]:
        await update.message.reply_text("已退出聊天模式。")
        return ConversationHandler.END

    ai = AIService()
    await update.message.reply_chat_action(ChatAction.TYPING)
    try:
        resp = await ai.call(
            RequestType.TEXT, contents=user_msg, use_search=True
        )
        await update.message.reply_text(resp)
        return ASK_CHAT
    except Exception as e:
        await update.message.reply_text(f"❌ AI 回應失敗：{e}")
        return ASK_CHAT


# --- Menu Flow Handlers removed: use /info and /esti commands directly ---


# --- News ---
async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Retrieve Parser from bot_data (injected in main.py)
    news_parser: NewsParser = context.bot_data.get("news_parser")
    if not news_parser:
        # Fallback if not injected, though it should be
        news_parser = NewsParser()

    # Expanded News Menu
    reply_markup = InlineKeyboardMarkup(_build_news_main_keyboard())
    await update.message.reply_text("請選擇新聞來源：", reply_markup=reply_markup)


async def news_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    news_parser: NewsParser = context.bot_data.get("news_parser") or NewsParser()
    data = query.data

    today_date = datetime.now().strftime("%Y-%m-%d")

    # --- Menus ---
    if data == "news_main_menu":
        # Back to Main News Menu
        reply_markup = InlineKeyboardMarkup(_build_news_main_keyboard())
        await query.edit_message_text("請選擇新聞來源：", reply_markup=reply_markup)
        return

    if data == "news_vocus_menu":
        # Vocus Submenu
        keyboard = [
            [InlineKeyboardButton("全部 (All)", callback_data="news_vocus_all")],
            [InlineKeyboardButton("ieObserve", callback_data="news_vocus_ieobserve")],
            [InlineKeyboardButton("Miula", callback_data="news_vocus_miula")],
            [InlineKeyboardButton("黑洞資本 (Black Hole)", callback_data="news_vocus_blackhole")],
            [InlineKeyboardButton("🔙 回新聞選單", callback_data="news_main_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("與 Vocus 相關的追蹤者：", reply_markup=reply_markup)
        return

    # --- Fetching Logic ---
    news_list = []
    source_title = "News"

    # Standard Sources
    if data == "news_cnyes":
        source_title = "CNYES Headline"
        url = "https://api.cnyes.com/media/api/v1/newslist/category/headline"
        news_list = await news_parser.fetch_news_list(url, news_number=15)
    elif data == "news_google":
        source_title = "Google News"
        url = "https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        news_list = await news_parser.fetch_news_list(url, news_number=15)
    elif data == "news_moneydj":
        source_title = "MoneyDJ"
        news_list = await news_parser.get_moneydj_report()
    elif data == "news_yahoo":
        source_title = "Yahoo TW"
        news_list = await news_parser.get_yahoo_tw_report()
    elif data == "news_udn":
        source_title = "UDN News"
        news_list = await news_parser.get_udn_report()
    elif data == "news_uanalyze":
        source_title = "UAnalyze"
        news_list = await news_parser.get_uanalyze_report()
    elif data == "news_macromicro":
        source_title = "MacroMicro"
        news_list = await news_parser.get_macromicro_report()
    elif data == "news_finguider":
        source_title = "FinGuider"
        news_list = await news_parser.get_finguider_report()
    elif data == "news_fintastic":
        source_title = "Fintastic"
        news_list = await news_parser.get_fintastic_report()
    elif data == "news_forecastock":
        source_title = "Forecastock"
        news_list = await news_parser.get_forecastock_report()
    elif data == "news_ndai":
        source_title = "NewsDigest AI"
        news_list = await news_parser.get_news_digest_ai_report()
    elif data == "news_fugle":
        source_title = "Fugle"
        url = "https://blog.fugle.tw/"
        news_list = await news_parser.get_fugle_report(url)
    elif data == "news_sinotrade_industry":
        source_title = "SinoTrade｜3分鐘產業百科"
        news_list = await news_parser.get_sinotrade_industry_report(limit=15)
    elif data == "news_pocket_report":
        source_title = "Pocket｜研究報告"
        news_list = await news_parser.get_pocket_school_report(limit=15)

    # Vocus Handlers
    elif data.startswith("news_vocus"):
        source_title = "Vocus"
        vocus_users = get_settings().VOCUS_USERS

        target_users = []
        if data == "news_vocus_all":
            target_users = vocus_users
            source_title = "Vocus (All)"
        else:
            key = data.replace("news_vocus_", "")
            # Match by substring in user id
            matched = [u for u in vocus_users if key in u.lower()]
            if matched:
                target_users = matched
                source_title = f"Vocus ({key})"

        for v_user in target_users:
            res = await news_parser.get_vocus_articles(v_user)
            if res:
                news_list.extend(res)

    # --- Display ---
    if not news_list:
        back_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 回上一頁", callback_data="news_main_menu")]]
        )
        await query.edit_message_text(
            "❌ 找不到新聞或該來源尚未支援。", reply_markup=back_markup
        )
        return

    # Format news
    msg = f"📅 **{source_title}** ({today_date})\n\n"
    for news in news_list[:10]:
        title = news["title"].replace("[", "(").replace("]", ")")
        msg += f"• [{title}]({news['url']})\n"

    # Add Back Button
    # If in Vocus submenu, maybe back to Vocus menu? But simplier to Main Menu for consistent UX.
    # Or checking data startswith.
    back_callback = "news_vocus_menu" if data.startswith("news_vocus") else "news_main_menu"

    keyboard = [[InlineKeyboardButton("🔙 回上一頁", callback_data=back_callback)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        msg,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )


# --- Google News ---
async def google_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search Google News. Usage: /google <keyword>"""
    if not context.args:
        await update.message.reply_text("❌ 用法：/google <關鍵字>")
        return

    keyword = " ".join(context.args)
    news_parser: NewsParser = context.bot_data.get("news_parser") or NewsParser()

    url = f"https://news.google.com/rss/search?q={quote(keyword)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    news_list = await news_parser.fetch_news_list(url)

    if not news_list:
        await update.message.reply_text("❌ 找不到相關新聞。")
        return

    msg = f"🔍 '{keyword}' 搜尋結果：\n\n"
    for news in news_list[:8]:
        title = news["title"].replace("[", "(").replace("]", ")")
        msg += f"• [{title}]({news['url']})\n"
    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
    )


# --- UAnalyze AI / MEGA ---

async def ua_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ua 2330 2317 — UAnalyze AI 多題分析"""
    if not context.args:
        await update.message.reply_text("❌ 用法：/ua <股號> [股號...]")
        return
    from ..services.uanalyze_ai import analyze_stock
    stocks = context.args
    await update.message.reply_text(f"⏳ 分析中：{', '.join(stocks)}")
    for stock in stocks:
        await update.message.reply_chat_action(ChatAction.TYPING)
        try:
            md = await analyze_stock(stock)
            f = io.BytesIO(md.encode("utf-8"))
            await update.message.reply_document(
                document=InputFile(f, filename=f"UA_{stock}.md"),
                caption=f"✅ {stock} 完成",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ {stock} 失敗：{str(e)[:200]}")


async def uask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/uask 2330 問題 — UAnalyze AI 自訂問題"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("❌ 用法：/uask <股號> <問題>")
        return
    from ..services.uanalyze_ai import analyze_stock
    stock = context.args[0]
    prompt = " ".join(context.args[1:])
    await update.message.reply_chat_action(ChatAction.TYPING)
    try:
        md = await analyze_stock(stock, prompts=[prompt])
        f = io.BytesIO(md.encode("utf-8"))
        await update.message.reply_document(
            document=InputFile(f, filename=f"Ask_{stock}.md"), caption=f"✅ {stock}",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 失敗：{str(e)[:200]}")


async def mega_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mega y 企劃 — MEGA 搜尋下載 (y=拉取 n=暫存)"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("❌ 用法：/mega y|n <關鍵字...>")
        return
    from ..services.mega_download import mega_search_and_download_async
    should_fetch = context.args[0].lower() != "n"
    keywords = context.args[1:]
    await update.message.reply_text(f"🚀 MEGA {'拉取' if should_fetch else '暫存'}：{', '.join(keywords)}")
    result = await mega_search_and_download_async(should_fetch, keywords)
    await update.message.reply_text(result[-4096:])


async def umon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/umon — 手動觸發 UAnalyze 監控檢查"""
    from ..services.uanalyze_monitor import check_new_reports

    settings = get_settings()
    if not settings.UANALYZE_API_URL:
        await update.message.reply_text("❌ UANALYZE_API_URL 未設定")
        return

    await update.message.reply_text("🔍 檢查 UAnalyze 新報告中...")
    bot = context.bot
    count = await check_new_reports(bot=bot)
    if count:
        await update.message.reply_text(f"✅ 發現並推播 {count} 則新報告")
    else:
        await update.message.reply_text("📭 無新報告")


async def sub_umon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sub_umon — 將目前聊天室綁定為 UAnalyze 報告推播目標"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if not sub:
                sub = Subscriber(chat_id=chat_id, topic_id=topic_id)
            sub.umon_enabled = True
            session.add(sub)
            session.commit()

    await asyncio.to_thread(_do)
    parts = [f"✅ 已新增 UAnalyze 推播目標\nChat ID: <code>{chat_id}</code>"]
    if topic_id:
        parts.append(f"Topic ID: <code>{topic_id}</code>")
    await update.message.reply_text("\n".join(parts), parse_mode="HTML")


async def unsub_umon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unsub_umon — 取消目前聊天室的 UAnalyze 報告推播"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if sub and sub.umon_enabled:
                sub.umon_enabled = False
                session.add(sub)
                session.commit()
                return True
            return False

    found = await asyncio.to_thread(_do)
    if found:
        await update.message.reply_text("✅ 已移除此聊天室的 UAnalyze 推播")
    else:
        await update.message.reply_text("ℹ️ 此聊天室未綁定")


async def sub_daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """訂閱每日分析推播。"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if not sub:
                sub = Subscriber(chat_id=chat_id, topic_id=topic_id)
            sub.daily_analysis_enabled = True
            session.add(sub)
            session.commit()

    await asyncio.to_thread(_do)
    await update.message.reply_text("✅ 已訂閱每日分析推播！")


async def unsub_daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消訂閱每日分析推播。"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if sub and sub.daily_analysis_enabled:
                sub.daily_analysis_enabled = False
                session.add(sub)
                session.commit()
                return True
            return False

    found = await asyncio.to_thread(_do)
    if found:
        await update.message.reply_text("❌ 已取消每日分析推播。")
    else:
        await update.message.reply_text("您尚未訂閱每日分析推播。")


async def sub_spike_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """訂閱收盤爆量推播。"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if not sub:
                sub = Subscriber(chat_id=chat_id, topic_id=topic_id)
            sub.spike_enabled = True
            session.add(sub)
            session.commit()

    await asyncio.to_thread(_do)
    await update.message.reply_text("✅ 已訂閱收盤爆量推播！")


async def unsub_spike_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消訂閱收盤爆量推播。"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if sub and sub.spike_enabled:
                sub.spike_enabled = False
                session.add(sub)
                session.commit()
                return True
            return False

    found = await asyncio.to_thread(_do)
    if found:
        await update.message.reply_text("❌ 已取消收盤爆量推播。")
    else:
        await update.message.reply_text("您尚未訂閱收盤爆量推播。")


async def sub_vix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """訂閱 VIX 警報推播。"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if not sub:
                sub = Subscriber(chat_id=chat_id, topic_id=topic_id)
            sub.vix_enabled = True
            session.add(sub)
            session.commit()

    await asyncio.to_thread(_do)
    await update.message.reply_text("✅ 已訂閱 VIX 警報推播！")


async def unsub_vix_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消訂閱 VIX 警報推播。"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if sub and sub.vix_enabled:
                sub.vix_enabled = False
                session.add(sub)
                session.commit()
                return True
            return False

    found = await asyncio.to_thread(_do)
    if found:
        await update.message.reply_text("❌ 已取消 VIX 警報推播。")
    else:
        await update.message.reply_text("您尚未訂閱 VIX 警報推播。")


# --- Research (Files) ---
async def research_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 請提供欲研究之資料，📝 文字與 📎 檔案皆可（可多份）：\n(Send /rq when done)"
    )
    context.user_data["research_materials"] = []
    return ASK_RESEARCH


async def research_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Collect materials
    materials = context.user_data.get("research_materials", [])

    if update.message.document:
        doc = update.message.document
        file_name = doc.file_name.lower()
        if not file_name.endswith((".docx", ".doc", ".pdf")):
            await update.message.reply_text("這個檔案格式我還不支援喔！")
            return ASK_RESEARCH

        try:
            # Download file
            new_file = await doc.get_file()
            bio = io.BytesIO()
            await new_file.download_to_memory(out=bio)
            bio.seek(0)

            if file_name.endswith((".docx", ".doc")):
                try:
                    document = DocxDocument(bio)
                    text_content = "\n".join([para.text for para in document.paragraphs])
                    materials.append(("text/plain", text_content))  # Treat as text
                    await update.message.reply_text(f"✅ 已接收 Word 檔案: {doc.file_name}")
                    context.user_data["research_materials"] = materials
                    return ASK_RESEARCH
                except Exception as e:
                    logger.error(f"Docx read error: {e}")
                    await update.message.reply_text(f"❌ 無法讀取 Word 檔案: {e}")
            else:
                # PDF or others
                materials.append(("application/pdf", bio.getvalue()))
                await update.message.reply_text(f"✅ 已接收 PDF 檔案: {doc.file_name}")

        except Exception as e:
            await update.message.reply_text(f"❌ 檔案下載失敗: {e}")

    elif update.message.text and not update.message.text.startswith("/"):
        materials.append(("text/plain", update.message.text))
        await update.message.reply_text("✅ 已記錄文字筆記")

    context.user_data["research_materials"] = materials
    return ASK_RESEARCH


async def research_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    materials = context.user_data.get("research_materials", [])

    if not materials:
        await update.message.reply_text("❌ 尚未提供任何資料，操作已取消。")
        return ConversationHandler.END

    sent_msg = await update.message.reply_text("⌛ 正在為您生成研究報告，請稍候... 📊📄")

    ai = AIService()
    try:
        # Prompt
        prompt = "根據提供的報告整理出常見投資問題、重點資訊與詳細回答，並用繁體中文回答"

        # Combine materials
        contents = []
        text_accum = ""

        for mime, data in materials:
            if mime == "text/plain":
                text_accum += f"\n\n{data}"
            else:
                contents.append((mime, data))

        if text_accum:
            prompt += f"\n\n[附帶文字內容]:\n{text_accum}"

        # If we have only text and no files, use RequestType.TEXT
        if not contents:
            response = await ai.call(RequestType.TEXT, contents=prompt, use_search=False)
        else:
            response = await ai.call(RequestType.FILE, contents=contents, prompt=prompt)

        if response:
            f = io.BytesIO(response.encode("utf-8"))
            f.name = "Research_Report.md"
            await update.message.reply_document(
                document=InputFile(f, filename="Research_Report.md"),
                caption="這是您的研究分析報告 📄",
                reply_to_message_id=sent_msg.message_id,
            )
        else:
            await update.message.reply_text("❌ AI 分析失敗，請稍後再試。")

    except Exception as e:
        logger.error(f"Research error: {e}")
        await update.message.reply_text(f"❌ 分析過程發生錯誤: {e}")

    # Clear data
    context.user_data["research_materials"] = []
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("已取消操作。")
    context.user_data.clear()
    return ConversationHandler.END


# --- Subscribe ---


def _get_topic_id(update: Update) -> int | None:
    return getattr(update.message, "message_thread_id", None)


def _find_subscriber(session, chat_id: int, topic_id: int | None):
    return session.exec(
        select(Subscriber).where(
            Subscriber.chat_id == chat_id, Subscriber.topic_id == topic_id
        )
    ).first()


async def sub_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if not sub:
                sub = Subscriber(chat_id=chat_id, topic_id=topic_id, news_enabled=True)
                session.add(sub)
                session.commit()
                return "new"
            if not sub.news_enabled:
                sub.news_enabled = True
                session.add(sub)
                session.commit()
                return "reactivated"
            return "already"

    result = await asyncio.to_thread(_do)
    if result == "new":
        await update.message.reply_text("✅ 已訂閱！")
    elif result == "reactivated":
        await update.message.reply_text("✅ 已恢復訂閱！")
    else:
        await update.message.reply_text("您已經是訂閱者囉！")


async def unsub_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if sub and sub.news_enabled:
                sub.news_enabled = False
                session.add(sub)
                session.commit()
                return True
            return False

    found = await asyncio.to_thread(_do)
    if found:
        await update.message.reply_text("❌ 已取消訂閱。")
    else:
        await update.message.reply_text("您尚未訂閱。")


async def sub_ispike_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """訂閱盤中爆量自動通知。"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if not sub:
                sub = Subscriber(chat_id=chat_id, topic_id=topic_id)
            sub.ispike_enabled = True
            session.add(sub)
            session.commit()

    await asyncio.to_thread(_do)
    await update.message.reply_text("✅ 已訂閱盤中爆量通知！\n交易時段每 5 分鐘自動掃描，有爆量股立即推播。")


async def unsub_ispike_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消訂閱盤中爆量自動通知。"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if sub and sub.ispike_enabled:
                sub.ispike_enabled = False
                session.add(sub)
                session.commit()
                return True
            return False

    found = await asyncio.to_thread(_do)
    if found:
        await update.message.reply_text("❌ 已取消盤中爆量通知訂閱。")
    else:
        await update.message.reply_text("您尚未訂閱盤中爆量通知。")


async def sub_senti_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """訂閱情緒警報（個股急轉 + 市場轉變）。"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if not sub:
                sub = Subscriber(chat_id=chat_id, topic_id=topic_id)
            sub.sentiment_alert_enabled = True
            session.add(sub)
            session.commit()

    await asyncio.to_thread(_do)
    await update.message.reply_text("✅ 已訂閱情緒警報！\n個股情緒急轉、市場情緒轉變時自動通知。")


async def unsub_senti_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消訂閱情緒警報。"""
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    def _do():
        with Session(engine) as session:
            sub = _find_subscriber(session, chat_id, topic_id)
            if sub and sub.sentiment_alert_enabled:
                sub.sentiment_alert_enabled = False
                session.add(sub)
                session.commit()
                return True
            return False

    found = await asyncio.to_thread(_do)
    if found:
        await update.message.reply_text("❌ 已取消情緒警報訂閱。")
    else:
        await update.message.reply_text("您尚未訂閱情緒警報。")


# --- Watchlist ---
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,31}$")


def _normalize_ticker(raw: str) -> str | None:
    ticker = raw.strip().upper()
    if not ticker:
        return None
    if not _TICKER_RE.fullmatch(ticker):
        return None
    return ticker


async def name_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch and reply the company name for a ticker (best-effort)."""
    usage = "用法：/name <ticker>"
    if not getattr(context, "args", None):
        await update.message.reply_text(usage)
        return

    ticker = _normalize_ticker(str(context.args[0]))
    if not ticker:
        await update.message.reply_text("❌ Ticker 格式不正確")
        return

    data, _from_cache = await StockService.get_or_analyze_stock(ticker)
    if not data or "error" in data:
        await update.message.reply_text(
            f"找不到公司名稱：{data.get('error') if isinstance(data, dict) else 'Unknown error'}"
        )
        return

    name = data.get("name") or ticker
    await update.message.reply_text(f"公司名稱：{name}\nTicker：{ticker}")


def _format_watchlist(chat_id: int) -> str:
    """Format the full watchlist for a chat, grouped by user."""
    with Session(engine) as session:
        items = session.exec(
            select(WatchlistEntry)
            .where(WatchlistEntry.chat_id == chat_id)
            .order_by(WatchlistEntry.user_id, WatchlistEntry.ticker)
        ).all()
        if not items:
            return "📌 目前沒有自選股"

        tickers = list({it.ticker for it in items})
        stocks = session.exec(
            select(StockData).where(StockData.ticker.in_(tickers))
        ).all()
    price_map = {s.ticker: s.price for s in stocks}

    # Group by user
    grouped: dict[str, list[WatchlistEntry]] = {}
    for it in items:
        name = it.user_name or str(it.user_id)
        grouped.setdefault(name, []).append(it)

    lines = ["📌 自選股清單\n"]
    for user_name, entries in grouped.items():
        lines.append(f"👤 {user_name}:")
        for i, e in enumerate(entries, 1):
            alias = f" {e.alias}" if e.alias else ""
            date_str = e.created_at.strftime("%m/%d") if e.created_at else ""

            # Price & P/L
            cur_price = price_map.get(e.ticker)
            price_part = ""
            if e.added_price and cur_price:
                pnl = (cur_price - e.added_price) / e.added_price * 100
                price_part = f" ${e.added_price:.1f}→${cur_price:.1f} ({pnl:+.2f}%)"
            elif e.added_price:
                price_part = f" ${e.added_price:.1f}"
            elif cur_price:
                price_part = f" ${cur_price:.1f}"

            line = f"  {i}. {e.ticker}{alias}{price_part} {date_str}"
            if e.note:
                line += f"\n     📝 {e.note}"
            lines.append(line)
        lines.append("")

    return "\n".join(lines).rstrip()


def _update_user_name(session: Session, chat_id: int, user_id: int, user_name: str) -> None:
    """Update user_name on all entries for this user in this chat."""
    entries = session.exec(
        select(WatchlistEntry)
        .where(WatchlistEntry.chat_id == chat_id)
        .where(WatchlistEntry.user_id == user_id)
    ).all()
    for e in entries:
        if e.user_name != user_name:
            e.user_name = user_name
            session.add(e)


async def _resolve_alias_and_price(ticker: str) -> tuple[str | None, float | None]:
    """Look up stock name and price for a ticker."""
    def _from_db():
        with Session(engine) as session:
            stock = session.exec(select(StockData).where(StockData.ticker == ticker)).first()
            if stock:
                return (str(stock.name)[:MAX_ALIAS_LENGTH] if stock.name else None, stock.price)
            return None, None

    alias, price = await asyncio.to_thread(_from_db)
    if not alias and ticker.isdigit():
        try:
            data, _ = await StockService.get_or_analyze_stock(ticker)
            if isinstance(data, dict):
                alias = str(data["name"])[:MAX_ALIAS_LENGTH] if data.get("name") and data["name"] != ticker else alias
                price = data.get("price") or price
        except Exception:
            pass
    return alias, price


async def wadd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wadd <ticker> [備註] — 加入自選股"""
    usage = "用法：/wadd <股號> [備註]"
    if not getattr(context, "args", None):
        await update.message.reply_text(usage)
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        await update.message.reply_text("無法取得使用者資訊。")
        return

    ticker = _normalize_ticker(str(context.args[0]))
    if not ticker:
        await update.message.reply_text("❌ Ticker 格式不正確")
        return

    note = " ".join(str(a) for a in context.args[1:]).strip() or None
    user_name = update.effective_user.full_name or str(user_id)
    alias, price = await _resolve_alias_and_price(ticker)

    def _add():
        with Session(engine) as session:
            existing = session.exec(
                select(WatchlistEntry)
                .where(WatchlistEntry.chat_id == chat_id)
                .where(WatchlistEntry.user_id == user_id)
                .where(WatchlistEntry.ticker == ticker)
            ).first()
            if existing:
                return "exists"
            session.add(WatchlistEntry(
                chat_id=chat_id, user_id=user_id, ticker=ticker,
                alias=alias, added_price=price, user_name=user_name, note=note,
            ))
            _update_user_name(session, chat_id, user_id, user_name)
            session.commit()
            return "added"

    result = await asyncio.to_thread(_add)
    if result == "exists":
        await update.message.reply_text(f"ℹ️ 已存在：{ticker}")
        return

    alias_suffix = f"（{alias}）" if alias else ""
    price_suffix = f" ${price:.1f}" if price else ""
    msg = f"✅ 已加入：{ticker}{alias_suffix}{price_suffix}"
    watchlist = await asyncio.to_thread(_format_watchlist, chat_id)
    await update.message.reply_text(f"{msg}\n\n{watchlist}")


async def wdel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wdel <ticker> — 移除自選股"""
    usage = "用法：/wdel <股號>"
    if not getattr(context, "args", None):
        await update.message.reply_text(usage)
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        await update.message.reply_text("無法取得使用者資訊。")
        return

    ticker = _normalize_ticker(str(context.args[0]))
    if not ticker:
        await update.message.reply_text("❌ Ticker 格式不正確")
        return

    user_name = update.effective_user.full_name or str(user_id)

    def _del():
        with Session(engine) as session:
            entry = session.exec(
                select(WatchlistEntry)
                .where(WatchlistEntry.chat_id == chat_id)
                .where(WatchlistEntry.user_id == user_id)
                .where(WatchlistEntry.ticker == ticker)
            ).first()
            if not entry:
                return "not_found", None, None
            added_price = entry.added_price
            alias = entry.alias
            session.delete(entry)
            _update_user_name(session, chat_id, user_id, user_name)
            session.commit()
            return "deleted", added_price, alias

    status, added_price, alias = await asyncio.to_thread(_del)
    if status == "not_found":
        await update.message.reply_text(f"ℹ️ 不在清單：{ticker}")
        return

    # P/L message
    alias_suffix = f"（{alias}）" if alias else ""
    pnl_msg = ""
    if added_price:
        def _get_cur_price():
            with Session(engine) as session:
                stock = session.exec(select(StockData).where(StockData.ticker == ticker)).first()
                return stock.price if stock else None
        cur_price = await asyncio.to_thread(_get_cur_price)
        if cur_price:
            pnl = (cur_price - added_price) / added_price * 100
            if pnl > 0:
                pnl_msg = f"\n🎉 恭喜！{ticker} 獲利 {pnl:+.2f}%"
            else:
                pnl_msg = f"\n💪 下次加油！{ticker} 虧損 {pnl:+.2f}%"

    msg = f"✅ 已移除：{ticker}{alias_suffix}{pnl_msg}"
    watchlist = await asyncio.to_thread(_format_watchlist, chat_id)
    await update.message.reply_text(f"{msg}\n\n{watchlist}")


async def wlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wlist — 查看自選股清單"""
    chat_id = update.effective_chat.id
    watchlist = await asyncio.to_thread(_format_watchlist, chat_id)
    await update.message.reply_text(watchlist)


def _normalize_threads_username(raw: str) -> str | None:
    s = str(raw).strip().lstrip("@")
    if not s or not _THREADS_USERNAME_RE.match(s):
        return None
    return s


async def threads_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    在此聊天室訂閱 Threads 公開帳號，定時或手動推播新貼文。
    用法：
      /threads add <使用者名稱>
      /threads remove <使用者名稱>
      /threads list
      /threads bootstrap <使用者名稱>
      /threads check
    """
    usage = (
        "🧵 Threads 監控\n"
        "/threads add <使用者名稱> — 訂閱（不含 @）\n"
        "/threads remove <使用者名稱>\n"
        "/threads list\n"
        "/threads bootstrap <使用者名稱> — 只記錄現有貼文，不推播\n"
        "/threads check — 立即檢查此聊天室所有訂閱"
    )
    if not context.args:
        await update.message.reply_text(usage)
        return

    sub = str(context.args[0]).lower()
    chat_id = update.effective_chat.id
    topic_id = _get_topic_id(update)

    # Lazy import: playwright is an optional heavy dependency
    from ..services.threads_watch_service import MAX_SEEN_IDS, fetch_posts_playwright

    if sub == "list":
        def _list():
            with Session(engine) as session:
                items = session.exec(
                    select(ThreadsWatchEntry)
                    .where(ThreadsWatchEntry.chat_id == chat_id)
                    .where(ThreadsWatchEntry.topic_id == topic_id)
                    .order_by(ThreadsWatchEntry.threads_username)
                ).all()
                return [it.threads_username for it in items]

        usernames = await asyncio.to_thread(_list)
        if not usernames:
            await update.message.reply_text("📭 此聊天室尚無 Threads 訂閱")
            return
        lines = ["🧵 此聊天室 Threads 訂閱："]
        for u in usernames:
            lines.append(f"• @{u}")
        await update.message.reply_text("\n".join(lines))
        return

    if sub == "check":
        def _get_ids():
            with Session(engine) as session:
                items = session.exec(
                    select(ThreadsWatchEntry)
                    .where(ThreadsWatchEntry.chat_id == chat_id)
                    .where(ThreadsWatchEntry.topic_id == topic_id)
                ).all()
                return [it.id for it in items]

        item_ids = await asyncio.to_thread(_get_ids)
        if not item_ids:
            await update.message.reply_text("尚無訂閱。先 /threads add <使用者名稱>")
            return
        await update.message.reply_text("⏳ 檢查中（Playwright 約需數秒）…")
        total = 0
        last_err: str | None = None
        with Session(engine) as session:
            for row_id in item_ids:
                ent = session.get(ThreadsWatchEntry, row_id)
                if not ent:
                    continue
                n, err = await process_threads_watch_entry(context.bot, session, ent)
                total += n
                if err:
                    last_err = err
        if last_err and total == 0:
            await update.message.reply_text(f"❌ {last_err}")
        elif total:
            await update.message.reply_text(f"✅ 已送出 {total} 則新貼文")
        else:
            await update.message.reply_text("✅ 沒有新貼文")
        return

    if sub == "bootstrap":
        if len(context.args) < 2:
            await update.message.reply_text("/threads bootstrap <使用者名稱>")
            return
        user = _normalize_threads_username(context.args[1])
        if not user:
            await update.message.reply_text("使用者名稱格式不正確")
            return
        def _check_exists():
            with Session(engine) as session:
                return session.exec(
                    select(ThreadsWatchEntry)
                    .where(ThreadsWatchEntry.chat_id == chat_id)
                    .where(ThreadsWatchEntry.topic_id == topic_id)
                    .where(ThreadsWatchEntry.threads_username == user)
                ).first() is not None

        exists = await asyncio.to_thread(_check_exists)
        if not exists:
            await update.message.reply_text(f"請先 /threads add {user}")
            return
        await update.message.reply_text("⏳ 抓取頁面…")
        try:
            posts = await asyncio.to_thread(
                fetch_posts_playwright,
                f"https://www.threads.com/@{user}",
                90_000,
            )
        except Exception as e:
            await update.message.reply_text(f"❌ 失敗：{str(e)[:200]}")
            return
        if not posts:
            await update.message.reply_text("未取得貼文連結（頁面變更或需登入）")
            return

        ids = [p.post_id for p in posts][-MAX_SEEN_IDS:]

        def _save_ids():
            with Session(engine) as session:
                ent = session.exec(
                    select(ThreadsWatchEntry)
                    .where(ThreadsWatchEntry.chat_id == chat_id)
                    .where(ThreadsWatchEntry.topic_id == topic_id)
                    .where(ThreadsWatchEntry.threads_username == user)
                ).first()
                if not ent:
                    return False
                ent.seen_post_ids = json.dumps(ids, ensure_ascii=False)
                session.add(ent)
                session.commit()
                return True

        saved = await asyncio.to_thread(_save_ids)
        if not saved:
            await update.message.reply_text("訂閱已不存在，請重新 add")
            return
        await update.message.reply_text(f"✅ 已記錄 {len(ids)} 則現有貼文 id，之後只推播新貼文")
        return

    if sub not in ("add", "remove"):
        await update.message.reply_text(usage)
        return

    if len(context.args) < 2:
        await update.message.reply_text(usage)
        return

    user = _normalize_threads_username(context.args[1])
    if not user:
        await update.message.reply_text("使用者名稱格式不正確")
        return

    def _add_or_remove():
        with Session(engine) as session:
            existing = session.exec(
                select(ThreadsWatchEntry)
                .where(ThreadsWatchEntry.chat_id == chat_id)
                .where(ThreadsWatchEntry.topic_id == topic_id)
                .where(ThreadsWatchEntry.threads_username == user)
            ).first()
            if sub == "add":
                if existing:
                    return "exists"
                session.add(ThreadsWatchEntry(chat_id=chat_id, topic_id=topic_id, threads_username=user))
                session.commit()
                return "added"
            if not existing:
                return "not_found"
            session.delete(existing)
            session.commit()
            return "removed"

    result = await asyncio.to_thread(_add_or_remove)
    if result == "exists":
        await update.message.reply_text(f"ℹ️ 已訂閱 @{user}")
    elif result == "added":
        await update.message.reply_text(
            f"✅ 已訂閱 @{user}\n"
            f"建議：/threads bootstrap {user}\n"
            "（避免首次排程一次推播多則舊貼文）"
        )
    elif result == "not_found":
        await update.message.reply_text(f"ℹ️ 未訂閱 @{user}")
    else:
        await update.message.reply_text(f"✅ 已取消 @{user}")



# ─────────────────────────────────────────────────────────────────────
# 新聞情緒分析
# ─────────────────────────────────────────────────────────────────────


async def sentiment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """新聞情緒分析。

    用法：
      /senti 2330       → 查看個股近 7 天情緒趨勢
      /senti market     → 查看整體市場情緒
    """
    if not context.args:
        await update.message.reply_text(
            "用法：\n"
            "  /senti 2330  → 個股情緒趨勢\n"
            "  /senti market → 市場情緒摘要"
        )
        return

    target = context.args[0].strip().lower()
    await update.message.reply_chat_action(ChatAction.TYPING)

    from ..services.sentiment_service import SentimentService

    if target == "market":
        summary = await asyncio.to_thread(SentimentService.get_market_sentiment_summary)
        if summary["total"] == 0:
            await update.message.reply_text("📊 目前沒有情緒分析資料。")
            return

        total = summary["total"]
        pos_pct = summary["positive"] / total * 100
        neg_pct = summary["negative"] / total * 100
        neu_pct = summary["neutral"] / total * 100

        # 情緒指標
        if summary["avg_score"] > 0.2:
            mood = "😊 偏樂觀"
        elif summary["avg_score"] < -0.2:
            mood = "😟 偏悲觀"
        else:
            mood = "😐 中性"

        msg = (
            f"📊 *市場情緒摘要*（近 24 小時）\n\n"
            f"整體情緒：{mood}\n"
            f"情緒分數：{summary['avg_score']:+.3f}\n\n"
            f"📰 新聞總數：{total}\n"
            f"  🟢 正面：{summary['positive']} ({pos_pct:.0f}%)\n"
            f"  ⚪ 中性：{summary['neutral']} ({neu_pct:.0f}%)\n"
            f"  🔴 負面：{summary['negative']} ({neg_pct:.0f}%)\n"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        # 個股情緒
        ticker = target.upper()
        trend = await asyncio.to_thread(SentimentService.get_ticker_sentiment_trend, ticker)

        if trend["total"] == 0:
            await update.message.reply_text(f"📊 {ticker} 近 7 天沒有情緒分析資料。")
            return

        total = trend["total"]
        pos_pct = trend["positive"] / total * 100
        neg_pct = trend["negative"] / total * 100

        # 情緒趨勢圖（文字版）
        daily_chart = ""
        for d in trend["daily"]:
            bar_pos = "🟢" * d["positive"]
            bar_neg = "🔴" * d["negative"]
            bar_neu = "⚪" * d["neutral"]
            daily_chart += f"  {d['date']} {bar_pos}{bar_neu}{bar_neg} ({d['avg']:+.2f})\n"

        msg = (
            f"📊 *{ticker} 情緒趨勢*（近 7 天）\n\n"
            f"情緒分數：{trend['avg_score']:+.3f}\n"
            f"📰 相關新聞：{total} 則\n"
            f"  🟢 正面：{trend['positive']} ({pos_pct:.0f}%)\n"
            f"  🔴 負面：{trend['negative']} ({neg_pct:.0f}%)\n\n"
            f"📈 *每日趨勢*\n{daily_chart}"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

        # 檢查情緒急轉
        shift_warning = await asyncio.to_thread(
            SentimentService.check_sentiment_shift, ticker
        )
        if shift_warning:
            await update.message.reply_text(shift_warning)
