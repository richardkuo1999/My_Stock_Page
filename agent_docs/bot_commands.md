# Bot Commands

## Overview
All bot commands are defined in `analysis_bot/bot/handlers.py`.
Handler registration is in `analysis_bot/bot/main.py`.

## Command Reference

### `/start`
**Function:** `start_command()`

**Description:** 啟動機器人，回傳歡迎訊息並提示使用 `/help` 查看指令。

---

### `/help`
**Function:** `help_command()` / `help_callback_handler()`

**Description:** 顯示指令分類按鈕（InlineKeyboard），點選分類後展開該類別的指令說明，可返回分類選單。

**架構：**
- `_HELP_CATEGORIES` — 分類按鈕列表（10 類）
- `_HELP_PAGES` — 各分類的指令說明文字
- `help_callback_handler()` — 處理分類按鈕與返回按鈕

---

### `/menu`
**Function:** `menu_command()` / `menu_callback_handler()`

**Description:** 開啟互動式 InlineKeyboard 選單。使用者點選分類後展開子選單，可直接執行指令或將指令填入輸入框。

**架構：**
- `_MENU_CATEGORIES` — 主選單分類列表（9 類）
- `_MENU_PAGES` — 各分類的按鈕定義（`/` 開頭 = 填入輸入框，`!` 開頭 = 直接執行）
- `_build_menu_main_keyboard()` — 建構主選單鍵盤
- `_build_category_keyboard()` — 建構分類頁面鍵盤
- `_fake_context` — 注入 args 的 context wrapper，供 menu 呼叫 command handler

**Callback 路由：**
- `menu_back` → 返回主選單
- `menu_cat_*` → 展開分類頁面
- `menu_exec!*` → 執行對應指令

---

### `/info <股號>`
**Function:** `info_command()` / `run_info_analysis()`

**Description:** 查詢個股基本面、營收與 AI 總結報告。

**Services Used:**
- `LegacyMoneyDJ` — Scrapes MoneyDJ wiki
- `uanalyze_ai.analyze_stock()` — UAnalyze AI 分析（6 題精選 prompt，並行呼叫）
- `AIService` — 整合 MoneyDJ + UAnalyze 資料，搭配 Google search 產生總結報告

**Flow:**
1. 並行呼叫 MoneyDJ wiki + UAnalyze AI（`asyncio.gather`，任一失敗不影響另一個）
2. 合併兩個來源的內容
3. 送入 AI 產生繁體中文總結報告（含 Google 搜尋）
4. 回傳 Markdown 文件

**Example:** `/info 2330`

---

### `/esti <股號>`
**Function:** `esti_command()` / `run_esti_analysis()`

**Description:** 執行「樂活五線譜」與「均值回歸」估值分析。

**Services Used:**
- `StockService.get_or_analyze_stock()` — Cache-aware analysis
- `ReportGenerator.generate_telegram_report()` — Format output

**Example:** `/esti 2330`

---

### `/p <股號>`
**Function:** `price_command()`

**Description:** 即時股價 + 盤中走勢圖（台股 09:00–13:30）。

**Services Used:** `price_fetcher.fetch_price()`, `intraday_chart.render_intraday_chart()`

**Example:** `/p 2330`

---

### `/k <股號> [參數...]`
**Function:** `kline_command()`

**Description:** K 線圖（近 3 個月日線），支援自訂 MA 週期及技術指標 `rsi` `macd` `kd` `bb` `dmi`。

**Services Used:** `candlestick_chart.render_candlestick_chart()`（lazy import，依賴 Playwright）

**Example:** `/k 2330`、`/k 2330 rsi kd`、`/k 2330 bb`、`/k 2330 dmi macd`

---

### `/name <股號>`
**Function:** `name_command()`

**Description:** 查詢公司名稱。

**Service:** `StockService.get_or_analyze_stock()`

---

### `/vix`
**Function:** `vix_command()`

**Description:** 查詢 VIX 恐慌指數現值。

**Services Used:** `vix_fetcher.fetch_vix_snapshot()`, `format_vix_message()`

---

### `/spike [change|t1]`
**Function:** `spike_command()`

**Description:** 收盤爆量偵測。掃描台灣上市櫃股票，找出成交量 ≥ 1000 張且 ≥ 20 日均量 1.5 倍的個股。

**排序：**
- `/spike` — 按 MA20 倍數排序（預設）
- `/spike change` — 按漲幅排序
- `/spike t1` — 按前日倍數排序

**Services Used:**
- `VolumeSpikeScanner` — TWSE/TPEx + yfinance
- `spike_pager` — 分頁輸出
- `enrich_with_news` — Google News + AI 題材分析（可設定開關）

---

### `/ispike [change]`
**Function:** `intraday_spike_command()`

**Description:** 盤中爆量偵測（即時）。使用 MA20 快照 + Fugle 盤中資料。

**Services Used:** `IntradaySpikeScanner`, `spike_pager`

---

### `/sub_ispike` / `/unsub_ispike`
**Functions:** `sub_ispike_command()` / `unsub_ispike_command()`

**Description:** 訂閱/取消盤中爆量自動通知。

**Database:** `Subscriber` model（`ispike_enabled` 欄位）

---

### `/news`
**Function:** `news_command()` / `news_button_handler()`

**Description:** 開啟新聞來源 InlineKeyboard 選單，支援 15+ 個來源。

**共用函式：** `_build_news_main_keyboard()` — 新聞選單鍵盤（news_command 與 news_button_handler 共用）

**Service:** `NewsParser`

---

### `/google <關鍵字>`
**Function:** `google_command()`

**Description:** Google 新聞搜尋。直接指令，不再使用 ConversationHandler。

**Service:** `NewsParser.fetch_news_list()`

**Example:** `/google 台積電`

---

### `/chat [問題]`
**Function:** `chat_command()` / `chat_start()` / `chat_handle()`

**Description:**
- `/chat <問題>` — 單次 AI 回答
- `/chat`（無參數）— 進入持續對話模式（輸入 `exit` 或 `cancel` 離開）

**Service:** `AIService` with Gemini

---

### `/research`
**Entry:** `research_start()` → `research_handle()` → `research_finish()`

**Description:** 上傳 PDF/DOCX 文件，自動生成投資研究摘要。上傳完畢後輸入 `/rq` 產生報告。

**Service:** `AIService.call(RequestType.FILE, ...)`

---

### `/ua <股號> [股號...]`
**Function:** `ua_command()`

**Description:** UAnalyze AI 多題分析。對每個股號執行 30 個預設 prompt，回傳 Markdown 文件。

**Service:** `uanalyze_ai.analyze_stock()`

**Example:** `/ua 2330 2317`

---

### `/uask <股號> <問題>`
**Function:** `uask_command()`

**Description:** UAnalyze AI 自訂問題。

**Service:** `uanalyze_ai.analyze_stock(stock, prompts=[question])`

**Example:** `/uask 2330 近期營收？`

---

### `/umon`
**Function:** `umon_command()`

**Description:** 手動觸發 UAnalyze 報告監控檢查。

**Service:** `uanalyze_monitor.check_new_reports()`

---

### `/sub_umon`
**Function:** `sub_umon_command()`

**Description:** 訂閱 UAnalyze 報告推播（綁定目前聊天室）。

---

### `/unsub_umon`
**Function:** `unsub_umon_command()`

**Description:** 取消 UAnalyze 報告推播。

---

### `/mega y|n <關鍵字>`
**Function:** `mega_command()`

**Description:** MEGA 雲端搜尋下載。`y` = 拉取最新，`n` = 僅搜尋暫存。

**Service:** `mega_download.mega_search_and_download_async()`

**Example:** `/mega y 企劃`

---

### `/subscribe` / `/unsubscribe`
**Functions:** `subscribe_command()` / `unsubscribe_command()`

**Description:** 訂閱/取消每日推播（個股分析、新聞、Podcast 摘要）。DB 操作透過 `asyncio.to_thread` 執行。

**Database:** `Subscriber` model

---

### `/watch add|remove|list <股號> [別名]`
**Function:** `watch_command()`

**Description:** 管理個人自選股。

**Features:**
- Per-chat, per-user watchlist
- Auto-fetch company name as alias（台股）
- News notification integration（`check_news_job`）

**Database:** `WatchlistEntry` model

---

### `/gsheet add|del|list|sync <URL> [標籤]`
**Function:** `gsheet_command()`

**Description:** 管理 Google Sheets 自選股同步。用戶註冊公開試算表 URL 後，bot 每 5 分鐘自動抓取並同步到自選股清單。

**用法：**
- `/gsheet add <URL> [標籤]` — 註冊試算表（需為公開或「知道連結的人可檢視」）
- `/gsheet del <URL>` — 取消註冊
- `/gsheet list` — 查看已註冊的試算表
- `/gsheet sync` — 立即手動同步

**同步邏輯：**
- Sheet 新增 → 加入 WatchlistEntry
- Sheet 更新 → 覆蓋 WatchlistEntry（note、alias、price）
- Sheet 刪除 → 從 WatchlistEntry 移除
- 同一檔股票只存一筆，以 Google Sheet 為主覆蓋

**試算表格式（預期欄位）：**
B: 股票代號, C: 股票名稱, D: 新增日期, E: 狀態, F: 週期, G: 備註&策略, H: 現價, I: 參考損, J: 月成本, K: 持倉%, L: 近期動作

**Note 欄位格式：** `狀態:持有 | 週期:波段 | 策略:xxx | 停損:xxx | 倉位:★★★☆☆ | 動作:xxx`

**防呆驗證（add 時）：**
1. URL 必須包含 `docs.google.com/spreadsheets`
2. 試抓 CSV 確認試算表可存取
3. 解析確認有有效股票資料（B 欄為 4-6 碼數字）
4. 任一步驟失敗則拒絕註冊並提示原因

**通知：** 定時同步偵測到變更時，推播給所有 `/sub_wlist` 訂閱者，訊息包含新增/更新的股票明細。

**Database:** `GSheetSubscription`（註冊資訊）, `WatchlistEntry`（同步後的持股）

**Services:** `gsheet_monitor.gsheet_sync_job()`（定時任務）, `gsheet_monitor.gsheet_sync_for_user()`（手動同步）

---

### `/sub_wlist` / `/unsub_wlist`
**Functions:** `sub_wlist_command()` / `unsub_wlist_command()`

**Description:** 訂閱/取消自選股同步通知。當 Google Sheets 試算表有更新並同步後，推播變更明細到訂閱的聊天室。

**Database:** `Subscriber` model（`wlist_enabled` 欄位）

---

### `/threads add|remove|list|check|bootstrap <帳號>`
**Function:** `threads_command()`

**Description:** 訂閱 Threads 公開帳號，背景 job 定期用 Playwright 檢查新貼文並推播。

**用法：**
- `/threads add <帳號>` — 訂閱（不含 `@`）
- `/threads remove <帳號>` — 取消訂閱
- `/threads list` — 查看訂閱清單
- `/threads check` — 立即檢查新貼文
- `/threads bootstrap <帳號>` — 記錄現有貼文 id，避免首次大量推播

**Database:** `ThreadsWatchEntry`

---

### `/hold981 [date]` / `/hold888 [date]`
**Functions:** `hold981_command()` / `hold888_command()`

**Description:** 抓取 Blake Finance 持股變化。日期可選，格式 `YYYY-MM-DD`。

**Services Used:** `blake_chips_scraper.fetch_chips_data()` / `fetch_chips_data_888()`

---

### `/chatid`
**Function:** `chatid_command()`

**Description:** 查看目前 Chat ID。

---

## Conversation Handlers

| Handler | Entry | States | Fallbacks |
|---------|-------|--------|-----------|
| Research | `/research` | `ASK_RESEARCH`（收集文件） | `/rq`（完成）, `/cancel` |
| Chat | `/chat`（無參數） | `ASK_CHAT`（持續對話） | `/cancel`, `exit` |

兩者皆設定 `per_chat=False`（允許多使用者同時使用）和 `conversation_timeout=300`。

---

## Adding a New Command

1. 在 `handlers.py` 定義 handler function
2. 在 `main.py` 的 `create_bot_application()` 中註冊 `CommandHandler`
3. 更新 `help_command()` 的指令列表
4. 更新 `main.py` 中 `set_my_commands()` 的 BotCommand 列表
5. 如需加入 `/menu`，在 `_MENU_PAGES` 對應分類中新增按鈕
