import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from telegram.ext import AIORateLimiter

from ..config import get_settings

logger = logging.getLogger(__name__)
from ..services.news_parser import NewsParser
from .handlers import (
    ASK_CHAT,
    ASK_RESEARCH,
    cancel,
    chat_command,
    chat_handle,
    chatid_command,
    esti_command,
    google_command,
    help_callback_handler,
    help_command,
    hold888_command,
    hold981_command,
    info_command,
    intraday_spike_command,
    kline_command,
    mega_command,
    menu_callback_handler,
    menu_command,
    name_command,
    news_button_handler,
    news_command,
    price_command,
    price_news_callback,
    research_finish,
    research_handle,
    research_start,
    sentiment_command,
    spike_command,
    start_command,
    sub_ispike_command,
    sub_senti_command,
    sub_news_command,
    threads_command,
    ua_command,
    uask_command,
    umon_command,
    sub_umon_command,
    unsub_umon_command,
    sub_daily_command,
    unsub_daily_command,
    sub_spike_command,
    unsub_spike_command,
    sub_vix_command,
    unsub_vix_command,
    unsub_ispike_command,
    unsub_senti_command,
    unsub_news_command,
    vix_command,
    wadd_command,
    wdel_command,
    wlist_command,
)
from .jobs import check_news_job, threads_watch_job

settings = get_settings()

ALLOWED_CHATS_FILTER = filters.ALL


def create_bot_application() -> Application:
    """Create and configure the Telegram Bot Application."""
    if not settings.TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN not set. Bot will not start properly.")

    application = (
        Application.builder()
        .token(settings.TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .rate_limiter(AIORateLimiter())
        .connect_timeout(60.0)
        .read_timeout(60.0)
        .write_timeout(60.0)
        .pool_timeout(30.0)
        .build()
    )

    # Initialize Services
    application.bot_data["news_parser"] = NewsParser()

    # Commands
    f = ALLOWED_CHATS_FILTER
    application.add_handler(CommandHandler("start", start_command, filters=f))
    application.add_handler(CommandHandler("help", help_command, filters=f))
    application.add_handler(CommandHandler("info", info_command, filters=f))
    application.add_handler(CommandHandler("esti", esti_command, filters=f))
    application.add_handler(CommandHandler("news", news_command, filters=f))
    application.add_handler(CommandHandler("google", google_command, filters=f))
    application.add_handler(CommandHandler("sub_news", sub_news_command, filters=f))
    application.add_handler(CommandHandler("unsub_news", unsub_news_command, filters=f))
    application.add_handler(CommandHandler("wadd", wadd_command, filters=f))
    application.add_handler(CommandHandler("wdel", wdel_command, filters=f))
    application.add_handler(CommandHandler("wlist", wlist_command, filters=f))
    application.add_handler(CommandHandler("threads", threads_command, filters=f))
    application.add_handler(CommandHandler("name", name_command, filters=f))
    application.add_handler(CommandHandler("p", price_command, filters=f))
    application.add_handler(CommandHandler("k", kline_command, filters=f))
    application.add_handler(CommandHandler("hold981", hold981_command, filters=f))
    application.add_handler(CommandHandler("hold888", hold888_command, filters=f))
    application.add_handler(CommandHandler("spike", spike_command, filters=f))
    application.add_handler(CommandHandler("ispike", intraday_spike_command, filters=f))
    application.add_handler(CommandHandler("sub_ispike", sub_ispike_command, filters=f))
    application.add_handler(CommandHandler("unsub_ispike", unsub_ispike_command, filters=f))
    application.add_handler(CommandHandler("sub_senti", sub_senti_command, filters=f))
    application.add_handler(CommandHandler("unsub_senti", unsub_senti_command, filters=f))
    application.add_handler(CommandHandler("vix", vix_command, filters=f))
    application.add_handler(CommandHandler("chatid", chatid_command, filters=f))
    application.add_handler(CommandHandler("menu", menu_command, filters=f))
    application.add_handler(CommandHandler("ua", ua_command, filters=f))
    application.add_handler(CommandHandler("uask", uask_command, filters=f))
    application.add_handler(CommandHandler("umon", umon_command, filters=f))
    application.add_handler(CommandHandler("sub_umon", sub_umon_command, filters=f))
    application.add_handler(CommandHandler("unsub_umon", unsub_umon_command, filters=f))
    application.add_handler(CommandHandler("sub_daily", sub_daily_command, filters=f))
    application.add_handler(CommandHandler("unsub_daily", unsub_daily_command, filters=f))
    application.add_handler(CommandHandler("sub_spike", sub_spike_command, filters=f))
    application.add_handler(CommandHandler("unsub_spike", unsub_spike_command, filters=f))
    application.add_handler(CommandHandler("sub_vix", sub_vix_command, filters=f))
    application.add_handler(CommandHandler("unsub_vix", unsub_vix_command, filters=f))
    application.add_handler(CommandHandler("mega", mega_command, filters=f))
    application.add_handler(CommandHandler("senti", sentiment_command, filters=f))

    # Conversation: Research (per_chat=False allows concurrent users)
    research_conv = ConversationHandler(
        entry_points=[CommandHandler("research", research_start)],
        states={
            ASK_RESEARCH: [
                MessageHandler(
                    filters.Document.ALL | (filters.TEXT & ~filters.COMMAND),
                    research_handle,
                ),
            ]
        },
        fallbacks=[CommandHandler("rq", research_finish), CommandHandler("cancel", cancel)],
        per_chat=False,
        conversation_timeout=300,
    )
    application.add_handler(research_conv)

    # Conversation: Chat (per_chat=False allows concurrent users)
    chat_conv = ConversationHandler(
        entry_points=[CommandHandler("chat", chat_command)],
        states={
            ASK_CHAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handle)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^(cancel|exit)$"), cancel),
        ],
        per_chat=False,
        conversation_timeout=300,
    )
    application.add_handler(chat_conv)

    # Callbacks
    application.add_handler(CallbackQueryHandler(menu_callback_handler, pattern="^menu_"))
    application.add_handler(CallbackQueryHandler(help_callback_handler, pattern="^help_"))
    application.add_handler(CallbackQueryHandler(news_button_handler, pattern="^news_"))
    application.add_handler(CallbackQueryHandler(price_news_callback, pattern="^pnews:"))

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
