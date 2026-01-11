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
    FINMIND_TOKENS: List[str] = [] # Supports JSON list from .env
    NEWS_API_KEY: Optional[str] = None
    
    # AI Keys
    GEMINI_API_KEYS: List[str] = []
    GROQ_API_KEY: Optional[str] = None
    
    # Podcast
    PODCAST_SOURCE_IDS: List[str] = ['1500839292','1546879892', '1488295306', '1518952450', '1602637578', '1513810531']
    PODCAST_LOOKUP_URL: str = "https://itunes.apple.com/lookup?id="


    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

@lru_cache
def get_settings():
    return Settings()
