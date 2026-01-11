# 系統遷移進度詳報 (Migration Detail Report)

> **最後更新時間**: 2026-01-11
> **狀態**: ✅ 核心功能全數遷移完成 (Features Migrated)
> **版本**: 2.0 (FastAPI + SQLModel + Async Bot)

本文件詳細記錄從舊版 `My_Stock_Page` (Django) 遷移至新版 `analysis_bot` (FastAPI) 的完整差異對比。

---

## 🏗 1. 架構與技術棧對比 (Architecture Comparison)

| 比較項目 | 舊版 (`old/My_Stock_Page`) | 新版 (`analysis_bot`) | 遷移優勢 |
| :--- | :--- | :--- | :--- |
| **框架 (Framework)** | **Django** (MVT Pattern) | **FastAPI** (ASGI Microservice) | 啟動速度快，非阻塞 I/O 適合高並發 Bot 請求。 |
| **資料庫 (DB)** | SQLite (Django Context, `db.sqlite3`) | SQLite (**SQLModel/SQLAlchemy**, `stock_data.db`) | 移除 Django 依賴，採用現代化 Type Hinting ORM。 |
| **配置管理** | `config.py` + `settings.py` (分散) | `config.py` (**Pydantic Settings**) | 統一環境變數管理，型別安全。 |
| **機器人核心** | `python-telegram-bot` (同步/Polling) | `python-telegram-bot` (**全異步 Async**) | 正確處理 `async/await`，且與 FastAPI 共用 Event Loop。 |
| **排程器** | `APScheduler` (Blocking Thread) | `AsyncIOScheduler` | 排程任務完全異步，不阻塞網頁服務。 |
| **前端介面** | Django Template (各頁面獨立渲染) | **Vanilla JS + CSS (Single Page-like)** | 現代化 Glassmorphism UI，動態 fetch API 更新數據。 |

---

## 🔍 2. 詳細程式碼層級對比 (Code-Level Comparison)

### A. 資料模型 (Data Models)
*   **舊版**: 使用 `DAILY_LIST` 和 `USER_CHOICE` 表，內容僅為**純文字字串** (Space-separated tags)，難以查詢個別股票狀態。
*   **新版**: 
    *   `StockData`: 結構化每檔股票 (Ticker, Name, Price, Tags, AnalysisResult)。
    *   `SystemConfig`: 統一管理全域設定 (如 Daily Run Tags)。
    *   **優勢**: 可直接 SQL 查詢「哪些股票被低估」、「哪些是半導體股」，不再需要取出字串 parse。

### B. 財經新聞 (News Engine)
*   **舊版 (`cmd_googleNews`)**:
    *   僅簡單抓取 Google RSS。
    *   無儲存，每次查詢即時抓取 (慢)。
*   **新版 (`NewsParser` + `StockService`)**:
    *   **多來源**: 整合 UDN, Fugle, UAnalyze, Moneydj, Cnyes 等 8+ 來源。
    *   **智能去重**: 使用 `difflib` 比對標題相似度，過濾重複內容。
    *   **平衡抓取**: 確保每個來源 (如 Fugle, UDN) 都能在首頁露出，不會被大量發文的來源洗版。
    *   **持久化**: 所有新聞存入 DB，支援歷史回溯與全文搜尋。

### C. 股票分析 (Analysis Logic)
*   **舊版 (`calculator.py` + `views.py`)**:
    *   邏輯混雜在 View 中 (`InvestmentView.daily_run`)。
    *   依賴生成大量臨時 `.csv/.txt` 檔案供使用者下載。
*   **新版 (`StockService`)**:
    *   邏輯封裝於 Service 層，Bot 與 Web 共用同一套程式碼。
    *   **快取機制**: 實作 `6-Hour Cache`，避免短時間重複分析同一檔股票，大幅節省 API Quota。
    *   **即時回饋**: 分析結果直接寫入 DB，網頁刷新即看到更新 (Freshness Tag)。
  3.  **ETF 成分股自動同步**
    *   **狀態**: ✅ **已實作 (Implemented)**。
    *   **說明**: 系統已內建 `StockSelector` 服務，每日排程會自動至 MoneyDJ 爬取設定之 ETF (如 0050, 0056) 最新成分股並納入分析範圍。

### D. Podcast 摘要
*   **舊版**: 簡單的 `requests` 下載 + Gemini 摘要。常因 SSL 或 MIME type 錯誤失敗。
*   **新版**: 
    *   `PodcastService`: 增強錯誤處理 (Retry機制)。
    *   **自動化流程**: 排程每小時檢查 -> 下載 -> 轉文字 -> 摘要 -> 存檔 -> 推播 -> 清理暫存。

---

## ✅ 3. 功能遷移狀態 (Migration Status)

### 📊 核心功能
*   [x] **個股估值 (/esti)**: 完整遷移，支援 Markdown 美觀報告。
*   [x] **每日掃描 (Daily Run)**: 完整遷移，並優化為異步並發執行。
*   [x] **搜尋與研究 (/info, /research)**: 整合 Wiki 與 Gemini，支援多模態檔案輸入。
*   [x] **新聞聚合 (/news)**: 大幅增強，新增網頁版新聞牆與過濾器。

### 🌐 網頁介面 (Web Dashboard)
*   [x] **儀表板**: 全新設計，夜間模式/玻璃擬態風格。
*   [x] **即時篩選**: 支援 Ticker/Sector/Tag 搜尋。
*   [x] **設定頁面**: 圖形化介面管理「每日觀察清單」與「Token 設定」。
*   [x] **詳細頁**: 整合 TradingView Widget 與分析數據。

### ⚙️ 系統優化
*   [x] **Docker Ready**: 移除對本機路徑的硬編碼依賴。
*   [x] **Logs**: 統一使用 Python `logging` 模組，分層級記錄 (Info/Debug/Error)。

---

## 🔮 4. 未來展望 (Future Roadmap)

1.  **使用者帳戶系統**: 目前為單機/單一 Admin 模式，未來可整合 `FastAPI-Users` 支援多用戶訂閱不同清單。
2.  **更強的線圖**: 於 Web 詳細頁中繪製「本益比河流圖」或「股利折現圖」 (目前僅文字數據)。


---
*Created by Antigravity Agent*
