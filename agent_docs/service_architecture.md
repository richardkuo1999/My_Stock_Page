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

**Responsibility:** AI provider abstraction layer with automatic failover between Ollama and Gemini.

**Key Features:**
- Provider switching (Ollama Cloud / Gemini)
- API key rotation for Gemini (supports multiple keys)
- Web search integration (Ollama Cloud only)
- Model fallback chain for Gemini

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

**Responsibility:** Scrape estimated EPS and target price from Anue (鉅亨網 FactSet reports).

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
    ┌────┴────┬─────────┬────────────┐
    ▼         ▼         ▼            ▼
┌───────┐ ┌───────┐ ┌─────────┐ ┌──────────┐
│Stock  │ │ AISvc │ │ News    │ │ Report   │
│Service│ │       │ │ Parser  │ │Generator │
└───┬───┘ └───┬───┘ └────┬────┘ └────┬─────┘
    │         │          │           │
    ▼         ▼          ▼           │
┌─────────────────────────┐          │
│    StockAnalyzer        │          │
│  (orchestrates fetch)   │          │
└───────────┬─────────────┘          │
            │                        │
    ┌───────┼───────┬────────┐       │
    ▼       ▼       ▼        ▼       │
┌───────┐ ┌───────┐ ┌──────┐ ┌─────┐│
│Yahoo  │ │FinMind│ │ Anue  │ │Math ││
│Finance│ │ API   │ │Scrape │ │Utils││
└───────┘ └───────┘ └──────┘ └─────┘│
                                     │
                     ┌───────────────┘
                     ▼
            ┌─────────────────┐
            │   SQLModel DB   │
            │ (StockData, etc)│
            └─────────────────┘
```

## Adding a New Service

1. Create file in `analysis_bot/services/`
2. Import in `__init__.py` if needed
3. Use from handlers or other services via dependency injection