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

    global bot_app, _bot_app_lock
    _bot_app_lock = _aio.Lock()

    # Startup
    setup_logging()

    # Validate required config at startup
    missing = []
    if not settings.TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if settings.AI_PROVIDER == "gemini" and not settings.GEMINI_API_KEYS:
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
                    BotCommand("start", "主選單 Menu"),
                    BotCommand("news", "財經新聞 News"),
                    BotCommand("info", "個股分析 Analysis"),
                    BotCommand("esti", "估值報告 Valuation"),
                    BotCommand("p", "即時股價"),
                    BotCommand("hold981", "00981A持股變化"),
                    BotCommand("hold888", "00981A & 大額權證買超"),
                    BotCommand("spike", "爆量偵測 Volume Spike"),
                    BotCommand("research", "AI 研究 Research"),
                    BotCommand("google_news", "Google 新聞"),
                    BotCommand("chat", "AI 聊天 Chat"),
                    BotCommand("subscribe", "訂閱新聞 Subscribe"),
                    BotCommand("unsubscribe", "取消訂閱 Unsubscribe"),
                    BotCommand("watch", "自選股 Watchlist"),
                    BotCommand("threads", "Threads 新貼文"),
                    BotCommand("help", "幫助 Help"),
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
