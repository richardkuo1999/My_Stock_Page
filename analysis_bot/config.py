from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import List, Optional


class Settings(BaseSettings):
    APP_NAME: str = "My Stock Analysis Bot"
    DEBUG: bool = True

    # Telegram
    TELEGRAM_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Database
    DATABASE_URL: str = "sqlite:///./stock_data.db"

    # Financial Data
    FINMIND_TOKENS: List[str] = []  # Supports JSON list from .env
    NEWS_API_KEY: Optional[str] = None

    # News Source Toggles
    ENABLE_UDN_NEWS: bool = False
    ENABLE_YAHOO_NEWS: bool = False

    # AI Keys
    GEMINI_API_KEYS: List[str] = []
    GROQ_API_KEY: Optional[str] = None

    # AI Provider: "ollama" or "gemini"
    AI_PROVIDER: str = "ollama"  # Switch between "ollama" and "gemini"

    # Ollama
    OLLAMA_BASE_URL: str = (
        "https://ollama.com"  # Cloud mode; local: http://localhost:11434
    )
    OLLAMA_MODEL: str = "glm-5:cloud"
    OLLAMA_API_KEY: Optional[str] = None  # Required for Ollama Cloud

    # Podcast
    PODCAST_SOURCE_IDS: List[str] = [
        "1500839292",
        "1546879892",
        "1488295306",
        "1518952450",
        "1602637578",
        "1513810531",
    ]
    PODCAST_LOOKUP_URL: str = "https://itunes.apple.com/lookup?id="

    # Logging / Privacy
    # Optional salt for redacting Telegram IDs (chat_id/user_id) in logs.
    # If empty, logs will use masked form (keeps only last 4 chars).
    LOG_PII_SALT: str = ""

    # Parallel Analysis Settings
    MAX_CONCURRENT_ANALYSIS: int = 10  # Maximum concurrent stock analyses
    ANALYSIS_PROGRESS_INTERVAL: int = 50  # Send progress update every N stocks
    ANALYSIS_BATCH_SIZE: int = 100  # Batch size for database writes

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings():
    return Settings()
