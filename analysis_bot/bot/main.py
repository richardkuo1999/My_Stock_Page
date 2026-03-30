import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ..config import get_settings

logger = logging.getLogger(__name__)
from ..services.news_parser import NewsParser
from .handlers import (
    ASK_CHAT,
    ASK_GOOGLE_NEWS,
    ASK_RESEARCH,
    ASK_TICKER_ESTI,
    ASK_TICKER_INFO,
    _menu_breakout,
    cancel,
    chat_command,
    chat_handle,
    chat_start,
    chatid_command,
    esti_command,
    google_news_handle,
    google_news_start,
    handle_ticker_esti,
    handle_ticker_info,
    help_command,
    hold888_command,
    hold981_command,
    info_command,
    menu_settings_handler,
    menu_stock_esti_start,
    menu_stock_info_start,
    name_command,
    news_button_handler,
    news_command,
    price_command,
    research_finish,
    research_handle,
    research_start,
    spike_command,
    start_command,
    subscribe_command,
    threads_command,
    unsubscribe_command,
    vix_command,
    watch_command,
)
from .jobs import check_news_job, threads_watch_job

settings = get_settings()

# 只允許白名單內的 chat 使用 Bot
_ALLOWED_CHATS = {int(settings.TELEGRAM_CHAT_ID)} if settings.TELEGRAM_CHAT_ID else set()
ALLOWED_CHATS_FILTER = filters.Chat(chat_id=list(_ALLOWED_CHATS)) if _ALLOWED_CHATS else filters.ALL

# 主選單按鈕：在對話流程中點擊時，跳出並執行對應功能（須放在 state handler 之前）
MENU_BREAKOUT_HANDLERS = [
    MessageHandler(filters.Regex("^📰 最新新聞$"), _menu_breakout(news_command)),
    MessageHandler(filters.Regex("^🔥 爆量偵測$"), _menu_breakout(spike_command)),
    MessageHandler(filters.Regex("^⚙️ 設定/訂閱$"), _menu_breakout(menu_settings_handler)),
    MessageHandler(filters.Regex("^🔍 Google 新聞$"), _menu_breakout(google_news_start)),
    MessageHandler(filters.Regex("^💬 AI 聊天$"), _menu_breakout(chat_start)),
    MessageHandler(filters.Regex("^🔎 檔案 Summary$"), _menu_breakout(research_start)),
    MessageHandler(filters.Regex("^📊 公司介紹/分析$"), _menu_breakout(menu_stock_info_start)),
    MessageHandler(filters.Regex("^📈 估值報告$"), _menu_breakout(menu_stock_esti_start)),
]


def create_bot_application() -> Application:
    """Create and configure the Telegram Bot Application."""
    if not settings.TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN not set. Bot will not start properly.")

    # 提高 timeout 以因應 Telegram API 連線較慢（如 9+ 秒）
    application = (
        Application.builder()
        .token(settings.TELEGRAM_TOKEN)
        .connect_timeout(60.0)
        .read_timeout(60.0)
        .write_timeout(60.0)
        .pool_timeout(30.0)
        .build()
    )

    # Initialize Services
    application.bot_data["news_parser"] = NewsParser()

    # Commands（僅允許白名單 chat）
    f = ALLOWED_CHATS_FILTER
    application.add_handler(CommandHandler("start", start_command, filters=f))
    application.add_handler(CommandHandler("help", help_command, filters=f))
    application.add_handler(CommandHandler("info", info_command, filters=f))
    application.add_handler(CommandHandler("esti", esti_command, filters=f))
    application.add_handler(CommandHandler("news", news_command, filters=f))
    application.add_handler(CommandHandler("chat", chat_command, filters=f))
    application.add_handler(CommandHandler("subscribe", subscribe_command, filters=f))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_command, filters=f))
    application.add_handler(CommandHandler("watch", watch_command, filters=f))
    application.add_handler(CommandHandler("threads", threads_command, filters=f))
    application.add_handler(CommandHandler("name", name_command, filters=f))
    application.add_handler(CommandHandler("p", price_command, filters=f))
    application.add_handler(CommandHandler("hold981", hold981_command, filters=f))
    application.add_handler(CommandHandler("hold888", hold888_command, filters=f))
    application.add_handler(CommandHandler("spike", spike_command, filters=f))
    application.add_handler(CommandHandler("vix", vix_command, filters=f))
    application.add_handler(CommandHandler("chatid", chatid_command, filters=f))

    # Conversation: Research
    research_conv = ConversationHandler(
        entry_points=[
            CommandHandler("research", research_start),
            MessageHandler(filters.Regex("^🔎 檔案 Summary$"), research_start),
        ],
        states={
            ASK_RESEARCH: MENU_BREAKOUT_HANDLERS
            + [
                MessageHandler(
                    filters.Document.ALL | (filters.TEXT & ~filters.COMMAND),
                    research_handle,
                ),
                CallbackQueryHandler(research_finish, pattern="^research_done$"),
            ]
        },
        fallbacks=[CommandHandler("rq", research_finish), CommandHandler("cancel", cancel)],
    )
    application.add_handler(research_conv)

    # Conversation: Analysis Flow (Menu)
    analysis_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📊 公司介紹/分析$"), menu_stock_info_start),
            MessageHandler(filters.Regex("^📈 估值報告$"), menu_stock_esti_start),
        ],
        states={
            ASK_TICKER_INFO: MENU_BREAKOUT_HANDLERS
            + [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ticker_info)],
            ASK_TICKER_ESTI: MENU_BREAKOUT_HANDLERS
            + [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ticker_esti)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^cancel$"), cancel),
        ],
    )
    application.add_handler(analysis_conv)

    # Conversation: Google News
    google_news_conv = ConversationHandler(
        entry_points=[
            CommandHandler("google_news", google_news_start),
            MessageHandler(filters.Regex("^🔍 Google 新聞$"), google_news_start),
        ],
        states={
            ASK_GOOGLE_NEWS: MENU_BREAKOUT_HANDLERS
            + [MessageHandler(filters.TEXT & ~filters.COMMAND, google_news_handle)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^cancel$"), cancel),
        ],
    )
    application.add_handler(google_news_conv)

    # Conversation: Chat
    chat_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💬 AI 聊天$"), chat_start)],
        states={
            ASK_CHAT: MENU_BREAKOUT_HANDLERS
            + [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handle)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^(cancel|exit)$"), cancel),
        ],
    )
    application.add_handler(chat_conv)

    # Menu Button Handlers (Stateless)
    application.add_handler(MessageHandler(filters.Regex("^📰 最新新聞$"), news_command))
    application.add_handler(MessageHandler(filters.Regex("^🔥 爆量偵測$"), spike_command))
    application.add_handler(MessageHandler(filters.Regex("^⚙️ 設定/訂閱$"), menu_settings_handler))
    # AI Research Button - redirect to research_start (which is entry point for another conv)
    # But research_conv entry_points currently only has CommandHandler. Need to add Regex handler there.

    # Callbacks
    application.add_handler(CallbackQueryHandler(news_button_handler, pattern="^news_"))

    # Jobs
    if application.job_queue:
        application.job_queue.run_repeating(check_news_job, interval=600, first=30)
        if settings.THREADS_WATCH_INTERVAL_SEC > 0:
            application.job_queue.run_repeating(
                threads_watch_job,
                interval=settings.THREADS_WATCH_INTERVAL_SEC,
                first=90,
            )

    return application
