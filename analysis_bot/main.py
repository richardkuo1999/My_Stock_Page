from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.web import router as web_router
from .bot.main import create_bot_application
from .config import get_settings
from .database import create_db_and_tables
from .logging_conf import setup_logging
from .scheduler import shutdown_scheduler, start_scheduler
from .services.ai_service import AIService
from .services.news_parser import NewsParser

settings = get_settings()
_bot_app_lock = None  # initialized in lifespan to ensure event loop is running
bot_app = None

import logging

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _aio
    from concurrent.futures import ThreadPoolExecutor

    global bot_app, _bot_app_lock
    _bot_app_lock = _aio.Lock()

    # Increase default thread pool so yfinance batch downloads don't starve other tasks
    _aio.get_event_loop().set_default_executor(ThreadPoolExecutor(max_workers=32))

    # Startup
    setup_logging()

    # Validate required config at startup
    missing = []
    if not settings.TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not settings.GEMINI_API_KEYS:
        missing.append("GEMINI_API_KEYS")
    if missing:
        logger.warning(
            f"Missing configuration: {', '.join(missing)}. Some features will be disabled."
        )

    create_db_and_tables()

    # Start Scheduler
    start_scheduler()

    # Start Telegram Bot
    if settings.TELEGRAM_TOKEN:
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                bot_app = create_bot_application()

                # Initialize Services
                bot_app.bot_data["ai_service"] = AIService()
                bot_app.bot_data["news_parser"] = NewsParser()
                await bot_app.bot_data["news_parser"].init_session()

                await bot_app.initialize()
                await bot_app.start()

                # 清除上一次殘留的 polling 連線（解決 --reload 時的 Conflict 問題）
                await bot_app.bot.delete_webhook(drop_pending_updates=True)

                # Set Bot Commands (Persistent Menu)
                from telegram import BotCommand

                commands = [
                    BotCommand("menu", "📋 互動選單"),
                    BotCommand("help", "📖 完整指令"),
                    BotCommand("p", "💹 即時股價"),
                    BotCommand("k", "📈 K 線圖"),
                    BotCommand("info", "🏢 個股分析"),
                    BotCommand("esti", "🎯 估值報告"),
                    BotCommand("name", "🏷 公司名稱"),
                    BotCommand("spike", "🔥 收盤爆量"),
                    BotCommand("ispike", "⚡ 盤中爆量"),
                    BotCommand("sub_ispike", "🔔 訂閱盤中爆量"),
                    BotCommand("unsub_ispike", "🔕 取消盤中爆量"),
                    BotCommand("news", "📰 新聞選單"),
                    BotCommand("google", "🔍 Google 新聞"),
                    BotCommand("chat", "💬 AI 聊天"),
                    BotCommand("research", "📚 上傳研究"),
                    BotCommand("vix", "😱 VIX"),
                    BotCommand("ua", "🔬 UAnalyze 分析"),
                    BotCommand("uask", "💡 UAnalyze 問答"),
                    BotCommand("umon", "🔍 UAnalyze 監控"),
                    BotCommand("mega", "📥 MEGA 下載"),
                    BotCommand("wadd", "➕ 加入自選股"),
                    BotCommand("wdel", "➖ 移除自選股"),
                    BotCommand("wlist", "📋 自選股清單"),
                    BotCommand("threads", "🧵 Threads 追蹤"),
                    BotCommand("hold981", "🏦 00981A 持股"),
                    BotCommand("hold888", "🏦 大額權證"),
                    BotCommand("sub_news", "📰 訂閱新聞推播"),
                    BotCommand("unsub_news", "🔕 取消新聞推播"),
                    BotCommand("chatid", "🆔 Chat ID"),
                    BotCommand("senti", "📊 新聞情緒分析"),
                    BotCommand("sub_senti", "🔔 訂閱情緒警報"),
                    BotCommand("unsub_senti", "🔕 取消情緒警報"),
                ]
                await bot_app.bot.set_my_commands(commands)

                await bot_app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=["message", "callback_query"],
                )
                print("Bot started.")
                break  # Success, exit retry loop
            except Exception as e:
                logger.error(f"Telegram bot attempt {attempt}/{max_attempts} failed: {e}")
                # Clean up partial state before retry
                if bot_app:
                    try:
                        await bot_app.shutdown()
                    except Exception:
                        pass
                    bot_app = None
                if attempt < max_attempts:
                    logger.info("Retrying in 5 seconds...")
                    await _aio.sleep(5)
                else:
                    print("Telegram bot failed to start, continuing with web interface only.")

    print(f"Started {settings.APP_NAME}")
    yield
    # Shutdown
    if bot_app:
        try:
            if bot_app.bot_data.get("news_parser"):
                await bot_app.bot_data["news_parser"].close()
        except Exception as e:
            logger.warning(f"Error closing news_parser: {e}")
        try:
            if bot_app.updater and bot_app.updater.running:
                await bot_app.updater.stop()
        except Exception as e:
            logger.warning(f"Error stopping updater: {e}")
        try:
            await bot_app.stop()
        except Exception as e:
            logger.warning(f"Error stopping bot app: {e}")
        try:
            await bot_app.shutdown()
        except Exception as e:
            logger.warning(f"Error shutting down bot app: {e}")
        print("Bot stopped.")

    shutdown_scheduler()
    print("Shutting down...")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan, debug=settings.DEBUG)

# Mount Static
app.mount("/static", StaticFiles(directory="analysis_bot/static"), name="static")

# Include Routers
app.include_router(web_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
