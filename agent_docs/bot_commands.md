# Bot Commands

## Overview
All bot commands are defined in `analysis_bot/bot/handlers.py`.

## Command Reference

### `/start` and `/help`
**Function:** `start_command()` / `help_command()`

**Description:** Displays main menu with keyboard options:
- 最新新聞
- 公司介紹/分析
- 估值報告
- 檔案 Summary (Research)
- Google 新聞
- AI 聊天
- 設定/訂閱

---

### `/info <ticker>`
**Function:** `info_command()` / `run_info_analysis()`

**Description:** Get company information and AI-generated analysis.

**Services Used:**
- `LegacyMoneyDJ` - Scrapes MoneyDJ wiki
- `AIService` - Generates summary with Google search

**Example:** `/info 2330`

---

### `/esti <ticker>`
**Function:** `esti_command()` / `run_esti_analysis()`

**Description:** Stock valuation analysis using "樂活五線譜" algorithm.

**Services Used:**
- `StockService.get_or_analyze_stock()` - Cache-aware analysis
- `ReportGenerator.generate_telegram_report()` - Format output

**Example:** `/esti 2330`

---

### `/news`
**Function:** `news_command()` / `news_button_handler()`

**Description:** Fetch news from multiple sources with inline keyboard selection.

**Supported Sources:**
- CNYES (鉅亨網)
- Google News (TW)
- MoneyDJ, Yahoo 股市
- UDN, UAnalyze, MacroMicro
- FinGuider, Fintastic, Forecastock
- Vocus (方格子), NewsDigest AI
- Fugle Report, SinoTrade, Pocket

**Service:** `NewsParser`

---

### `/chat <message>`
**Function:** `chat_command()`

**Description:** One-off AI chat with search capability.

**Service:** `AIService` with Gemini provider

---

### `/subscribe` / `/unsubscribe`
**Functions:** `subscribe_command()` / `unsubscribe_command()`

**Description:** Manage push notifications for news and daily analysis.

**Database:** Uses `Subscriber` model

---

### `/watch add/remove/list <ticker> [alias]`
**Function:** `watch_command()`

**Description:** Manage personal watchlist with optional aliases.

**Database:** Uses `WatchlistEntry` model

**Features:**
- Per-chat, per-user watchlist
- Auto-fetch company name as alias (for TW stocks)
- News notification integration (see `check_news_job` in `jobs.py`)

---

### `/name <ticker>`
**Function:** `name_command()`

**Description:** Fetch company name for a ticker.

**Service:** `StockService.get_or_analyze_stock()`

---

### `/p <ticker>`
**Function:** `price_command()`

**Description:** 即時股價查詢（yfinance，台股約 15–20 分鐘延遲）。Telegram 指令須小寫。

**Services Used:** `price_fetcher.fetch_price()`

**Example:** `/p 2330`、`/p AAPL`

---

### `/threads`（Threads 新貼文推播）
**Function:** `threads_command()`

**Description:** 在**目前聊天室**（私聊或群組）訂閱 Threads 公開帳號；背景 job 會定期用 Playwright 檢查新貼文並推送到該聊天室。

**用法：**
- `/threads add <使用者名稱>` — 不含 `@`
- `/threads remove <使用者名稱>`
- `/threads list`
- `/threads bootstrap <使用者名稱>` — 只記錄頁面上現有貼文 id，避免首次大量推播
- `/threads check` — 立即檢查此聊天室所有訂閱

**設定：** `THREADS_WATCH_INTERVAL_SEC`（秒，`0` 表示關閉定時輪詢，仍可用 `/threads check`）。需安裝 Chromium：`playwright install chromium`。

**Database:** `ThreadsWatchEntry`

---

### `/hold981 [date]`
**Function:** `hold981_command()`

**Description:** 抓取 00981 持股變化（Blake Finance）。日期可選，格式 YYYY-MM-DD。

**Services Used:** `blake_chips_scraper.fetch_chips_data()`

**Example:** `/hold981` 或 `/hold981 2026-03-18`

---

### `/hold888 [date]`
**Function:** `hold888_command()`

**Description:** 抓取 Blake Finance CHIPS match_888 資金流向資料（00981A_match_888）。日期可選。

**Services Used:** `blake_chips_scraper.fetch_chips_data_888()`

**Example:** `/hold888` 或 `/hold888 2026-03-18`

---

### `/spike`
**Function:** `spike_command()`

**Description:** 手動觸發爆量偵測。掃描台灣上市櫃股票，找出成交量 ≥ 1000 張且 ≥ 20 日均量 1.5 倍的個股。完成後會自動擷取前 20 檔的題材與產業面消息（Google News + AI 分析）。

**Services Used:**
- `VolumeSpikeScanner` - TWSE/TPEx OpenAPI + yfinance
- `enrich_with_news` - Google News RSS + AIService（題材／產業分析）

**Example:** `/spike`

---

### Research Flow (Conversation Handler)
**Entry:** `/research` or "🔎 檔案 Summary" button

**States:**
- `ASK_RESEARCH` - Collect materials (text/PDF/docx)
- `/rq` - Finish and generate report

**Services Used:**
- `AIService.call(RequestType.FILE, ...)` - Multimodal analysis

---

### Chat Flow (Conversation Handler)
**Entry:** "💬 AI 聊天" button

**States:**
- `ASK_CHAT` - Persistent chat mode (type "exit" or "cancel" to leave)

---

## Adding a New Command

1. Define handler function in `handlers.py`
2. Register with `Application.builder().add_handler()`
3. If conversation handler, define states and transitions
4. Update help text in `start_command()`