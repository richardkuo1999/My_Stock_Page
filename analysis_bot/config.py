from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "My Stock Analysis Bot"
    DEBUG: bool = False

    # Telegram
    TELEGRAM_TOKEN: str = ""

    # Database
    DATABASE_URL: str = "sqlite:///./stock_data.db"

    # Financial Data
    FINMIND_TOKENS: list[str] = []  # Supports JSON list from .env
    NEWS_API_KEY: str | None = None
    # 富果行情 REST API：https://developer.fugle.tw/docs/data/http-api/getting-started/
    FUGLE_API_KEY: str | None = None

    # News Source Toggles
    ENABLE_UDN_NEWS: bool = False
    ENABLE_YAHOO_NEWS: bool = False

    # AI Keys
    GEMINI_API_KEYS: list[str] = []
    GROQ_API_KEY: str | None = None

    # Podcast
    PODCAST_SOURCE_IDS: list[str] = [
        "1500839292",
        "1546879892",
        "1488295306",
        "1518952450",
        "1602637578",
        "1513810531",
    ]
    PODCAST_LOOKUP_URL: str = "https://itunes.apple.com/lookup?id="

    # Web API
    WEB_API_KEY: str | None = None

    # Logging / Privacy
    # Optional salt for redacting Telegram IDs (chat_id/user_id) in logs.
    # If empty, logs will use masked form (keeps only last 4 chars).
    LOG_PII_SALT: str = ""

    # Threads 監控（Bot 指令 + 定時 job，需安裝 playwright）
    # 0 = 不啟用背景輪詢（仍可用 /threads check）
    THREADS_WATCH_INTERVAL_SEC: int = 900

    # 爆量偵測：是否擷取前 N 檔題材／新聞＋ AI（預設關閉，程式仍保留）
    SPIKE_NEWS_ENRICHMENT_ENABLED: bool = False

    # 爆量偵測：定時任務預設排序方式
    SPIKE_DEFAULT_SORT: str = "ratio"  # ratio | change

    # 盤中爆量偵測設定
    INTRADAY_SPIKE_ENABLED: bool = True
    INTRADAY_SPIKE_MIN_LOTS: int = 200           # 最低成交量門檻（張），高於收盤掃描避免誤報
    INTRADAY_SPIKE_BASE_RATIO: float = 1.5       # 基礎爆量閾值（依時段動態調整）

    # Vocus 追蹤帳號
    VOCUS_USERS: list[str] = ["@ieobserve", "@miula", "65ab564cfd897800018a88cc"]

    # Blake Finance CHIPS URL
    BLAKE_CHIPS_URL_981: str = "https://blake-finance-notes.org/chips_blake_finance/code_php/00981A.php"
    BLAKE_CHIPS_URL_888: str = "https://blake-finance-notes.org/chips_blake_finance/code_php/00981A_match_888.php"

    # UAnalyze
    UANALYZE_AI_URL_TEMPLATE: str = ""
    UANALYZE_API_URL: str = ""
    UANALYZE_KEYWORDS: str = ""  # comma-separated

    # MEGA
    MEGA_PUBLIC_URL: str = ""

    # Parallel Analysis Settings
    MAX_CONCURRENT_ANALYSIS: int = 10  # Maximum concurrent stock analyses
    ANALYSIS_PROGRESS_INTERVAL: int = 50  # Send progress update every N stocks
    ANALYSIS_BATCH_SIZE: int = 100  # Batch size for database writes

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings():
    return Settings()
