# Service Architecture

## Overview

The `analysis_bot/services/` directory contains the core business logic services that power the stock analysis Telegram bot. These services interact with each other and external data sources to provide comprehensive analysis capabilities.

## Key Services and Their Responsibilities

### StockAnalyzer (`stock_analyzer.py`)
**Location:** `analysis_bot/services/stock_analyzer.py`

**Responsibility:** Core service for comprehensive stock analysis and valuation.

**Key Dependencies:**
- `DataFetcher` - Yahoo Finance data
- `FinMindFetcher` - Taiwan stock PER/PBR data
- `AnueScraper` - Anue/FactSet estimated data
- `MathUtils` - Mean reversion calculations

**Main Method:**
```python
async def analyze_stock(self, ticker: str, lohas_years: float = 3.5) -> Dict[str, Any]
```

**Data Flow:**
1. Fetches basic price data from Yahoo Finance (via `DataFetcher`)
2. For TW stocks (numeric tickers), fetches PER/PBR from FinMind API
3. Scrapes estimated EPS/target price from Anue (鉅亨網)
4. Calculates mean reversion analysis using `MathUtils`
5. Compiles all data into a unified analysis result dictionary

---

### AIService (`ai_service.py`)
**Location:** `analysis_bot/services/ai_service.py`

**Responsibility:** AI provider abstraction layer using Google Gemini with automatic key rotation and model fallback.

**Key Features:**
- Multiple API key rotation (handles rate limits)
- Model fallback chain: `gemini-3-flash → gemini-2.5-flash → gemini-3-flash-lite → gemini-2.5-flash-lite`
- Google Search grounding (`use_search=True`)

**Usage Pattern:**
```python
ai = AIService()
response = await ai.call(RequestType.TEXT, contents=prompt, use_search=True)
```

---

### NewsParser (`news_parser.py`)
**Location:** `analysis_bot/services/news_parser.py`

**Responsibility:** Multi-source news aggregation and content extraction.

**Supported Sources:**
- UDN, CNYES, MoneyDJ, UAnalyze, Fugle
- Vocus, SinoTrade, Pocket, Yahoo TW
- NewsDigest AI, MacroMicro, FinGuider, Fintastic, Forecastock

**Key Methods:**
- `fetch_news_list()` - RSS feed parsing
- `fetch_news_content()` - Full article extraction with site-specific parsers
- Source-specific methods: `get_fugle_report()`, `get_sinotrade_industry_report()`, etc.

---

### StockService (`stock_service.py`)
**Location:** `analysis_bot/services/stock_service.py`

**Responsibility:** Database operations and caching layer for stock data.

**Key Methods:**
- `get_or_analyze_stock()` - Cache-first stock analysis with 6-hour TTL
- `get_recent_news()` - News retrieval with source diversity
- `get_daily_tags()` / `toggle_daily_tag()` - Daily analysis tag management

---

### MathUtils (`math_utils.py`)
**Location:** `analysis_bot/services/math_utils.py`

**Responsibility:** Statistical calculations for mean reversion analysis.

**Key Methods:**
- `std()` - Median-based standard deviation bands (legacy, uses median as TL)
- `quartile()` - Quartile calculation for PE/PB
- `percentile_rank()` - Percentile ranking
- `mean_reversion()` - Core mean reversion calculation (uses linear regression for TL)

---

### ReportGenerator (`report_generator.py`)
**Location:** `analysis_bot/services/report_generator.py`

**Responsibility:** Generate formatted analysis reports.

**Output Formats:**
- `generate_full_report()` - Detailed text report
- `generate_telegram_report()` - Telegram-optimized format

---

### DataFetcher (`data_fetcher.py`)
**Location:** `analysis_bot/services/data_fetcher.py`

**Responsibility:** Yahoo Finance data retrieval using yfinance library.

---

### FinMindFetcher (`finmind_fetcher.py`)
**Location:** `analysis_bot/services/finmind_fetcher.py`

**Responsibility:** Taiwan stock data from FinMind API with token rotation.

---

### AnueScraper (`anue_scraper.py`)
**Location:** `analysis_bot/services/anue_scraper.py`

**Responsibility:** Fetch estimated EPS and target price from Anue (鉅亨網 FactSet reports).

**Data Sources (priority order):**
1. **CNYES marketinfo JSON API** (`estimateProfit` endpoint) — 直接取得 FactSet 各年度 EPS 預估（feMedian/feMean），計算加權 EPS
2. **Yahoo search + HTML scraping** (fallback) — 搜尋鉅亨速報文章，解析 EPS 表格

**Key Methods:**
- `fetch_estimated_data()` — 取得最新加權 EPS（API → search fallback）
- `fetch_all_estimates()` — 取得所有年度 EPS 快照（用於 EPS momentum）
- `_fetch_eps_from_api()` / `_fetch_all_from_api()` — CNYES JSON API
- `_fetch_eps_from_search()` / `_process_article()` — Yahoo search + HTML fallback

---

### HTTP Session Factory (`http.py`)
**Location:** `analysis_bot/services/http.py`

**Responsibility:** 提供統一的 `aiohttp.ClientSession` 工廠函式，內建 certifi SSL 憑證。

**背景：** 所有 service 原本各自建立 `aiohttp.ClientSession()`，在某些環境（macOS、Docker）會遇到 SSL 憑證問題。統一改用 `create_session()` 確保所有 HTTP 請求使用 certifi 的 CA bundle。

**Usage:**
```python
from .http import create_session

async with create_session() as session:
    async with session.get(url) as resp:
        data = await resp.json()
```

**被使用的 service：** `news_parser`, `price_fetcher`, `stock_analyzer`, `market_data_fetcher`, `blake_chips_scraper`, `cnyes_quote_scraper`, `eps_momentum_service`, `intraday_chart`, `legacy_scraper`, `stock_selector`, `uanalyze_ai`, `uanalyze_monitor`

---

### UAnalyze AI (`uanalyze_ai.py`)
**Location:** `analysis_bot/services/uanalyze_ai.py`

**Responsibility:** 透過 UAnalyze API 對個股執行多題 AI 分析，回傳 Markdown 報告。

**Key Features:**
- 30 個預設分析 prompt（近況、產業趨勢、護城河、關稅影響等）
- 並發控制（`MAX_CONCURRENT_REQUESTS=5`）
- 隨機延遲避免 rate limit

**Main Methods:**
- `analyze_stock(stock, prompts=None)` — 執行完整分析，回傳 Markdown
- `fetch_completion(session, prompt, stock, semaphore, results)` — 單一 prompt 請求

**Configuration:** `UANALYZE_AI_URL_TEMPLATE`（Settings）

---

### UAnalyze Monitor (`uanalyze_monitor.py`)
**Location:** `analysis_bot/services/uanalyze_monitor.py`

**Responsibility:** 定時輪詢 UAnalyze API 檢查新報告，有新報告時推播至 Telegram。

**Key Features:**
- 狀態持久化（`data/uanalyze/last_seen_id.json`）
- 關鍵字高亮（HTML bold）
- 首次執行只記錄 state 不推播
- 含關鍵字的報告開啟通知音效

**Main Method:**
```python
async def check_new_reports(bot=None, dry_run=False) -> int
```

**排程：** `scheduler.py` 每 60 秒執行一次（需設定 `UANALYZE_API_URL`）

**Configuration:** `UANALYZE_API_URL`, `UANALYZE_KEYWORDS`, `TELEGRAM_AI_NEWS_CHAT_ID`, `TELEGRAM_AI_NEWS_TOPIC_ID`

---

### MEGA Download (`mega_download.py`)
**Location:** `analysis_bot/services/mega_download.py`

**Responsibility:** 透過 MEGAcmd CLI 搜尋並下載 MEGA 雲端檔案。

**Key Features:**
- 支援關鍵字搜尋
- `y` 模式：先 import 再搜尋下載
- `n` 模式：僅搜尋暫存區
- 自動跳過已下載檔案

**Main Method:**
```python
async def mega_search_and_download_async(should_fetch: bool, keywords: list[str]) -> str
```

**Prerequisites:** 需安裝 MEGAcmd（`brew install megacmd`）

**Configuration:** `MEGA_PUBLIC_URL`

---

## Data Flow Diagram

```
User Request (Telegram)
    │
    ▼
┌─────────────────┐
│   handlers.py   │ ─── Command parsing & routing
└────────┬────────┘
         │
    ┌────┴────┬─────────┬────────────┬──────────────┐
    ▼         ▼         ▼            ▼              ▼
┌───────┐ ┌───────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐
│Stock  │ │ AISvc │ │ News    │ │ Report   │ │UAnalyze  │
│Service│ │       │ │ Parser  │ │Generator │ │AI / MEGA │
└───┬───┘ └───┬───┘ └────┬────┘ └────┬─────┘ └────┬─────┘
    │         │          │           │             │
    ▼         ▼          ▼           │             │
┌─────────────────────────┐          │             │
│    StockAnalyzer        │          │             │
│  (orchestrates fetch)   │          │             │
└───────────┬─────────────┘          │             │
            │                        │             │
    ┌───────┼───────┬────────┐       │             │
    ▼       ▼       ▼        ▼       │             │
┌───────┐ ┌───────┐ ┌──────┐ ┌─────┐│             │
│Yahoo  │ │FinMind│ │ Anue  │ │Math ││             │
│Finance│ │ API   │ │Scrape │ │Utils││             │
└───────┘ └───────┘ └──────┘ └─────┘│             │
                                     │             │
                     ┌───────────────┘             │
                     ▼                             │
            ┌─────────────────┐                    │
            │   SQLModel DB   │                    │
            │ (StockData, etc)│                    │
            └─────────────────┘                    │
                                                   │
            ┌──────────────────────────────────────┘
            ▼
    ┌───────────────┐
    │  http.py      │ ← 所有 aiohttp 請求統一使用
    │ create_session│    certifi SSL context
    └───────────────┘

Scheduler (背景排程)
    │
    ├── daily_analysis_job → StockAnalyzer → DB
    ├── daily_volume_spike_job → VolumeSpikeScanner
    ├── check_news_job → NewsParser → DB → Telegram push
    ├── intraday_spike_scan_job → IntradaySpikeScanner
    ├── vix_check_job → VixFetcher
    ├── threads_watch_job → ThreadsWatchService (Playwright)
    └── uanalyze_monitor_job → UAnalyzeMonitor → Telegram push
```

## Adding a New Service

1. Create file in `analysis_bot/services/`
2. Use `from .http import create_session` for HTTP requests
3. Import in `__init__.py` if needed
4. Use from handlers or other services
5. Add configuration to `Settings` class in `config.py` if needed
