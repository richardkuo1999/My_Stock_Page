# 既有問題調查（未來處理）

<!-- labels: backlog, investigation -->

<!-- 與來源 B/C 引入同性質：未來待辦，非目前 uanalyze_cli 引入實作範圍 -->

本檔記錄兩個**既有**問題（非 uanalyze_cli 引入產生），使用者於 2026-08-23 規劃 uanalyze_cli 引入時提出，判定為**未來獨立處理**（比照來源 B/C 延後）。但在 uanalyze_cli 引入的**實作過程中須注意、不得惡化**（見各項「引入實作中的即時注意」）。

---

## INV-01 — agent/prompts.py 工具清單已有缺漏

**類型：** 調查（未來處理，tech-debt）

### 問題
使用者回報 `agent/prompts.py` 的 `SYSTEM_PROMPT` 工具清單「好像已經少東西了」。

### 現況事實（初查）
- `tools/` 有 7 個功能工具（get_stock_price / draw_kchart / fetch_news / uanalyze / fetch_threads / summarize_document / lookup_stock_name）。
- `SYSTEM_PROMPT` 列了編號 1–7，數量對得上，但**內容與工具實際能力不同步**：
  - `uanalyze.py` 工具說明列的分析面向與實際 `UA_PROMPTS`（32 項）不一致（prompt 只列約 22 項）。
  - `fetch_news` 的 `--all` / 個股 / `--limit` 參數是否描述完整待查。
  - 工具編號順序錯亂（prompt 內是 1,2,3,7,4,5,6）——不影響功能但易誤導維護。

### 待辦（未來）
- [ ] 逐一比對 `SYSTEM_PROMPT` 每個工具說明 vs 該工具實際 CLI 能力，補齊、修正順序。
- [ ] 考慮工具清單「單一事實來源」（各工具 `--describe` 輸出，prompt 動態組裝），根治「改工具忘記改 prompt」。
- [ ] 將 prompts.py 正式納入「文件同步紀律」清單。

### 引入實作中的即時注意
本次 8 張 ticket 每張驗收已含「`agent/prompts.py` 工具清單更新」——實作時**順便修正該工具既有描述缺漏**，而非只加新的。

---

## INV-02 — 執行指令/Agent 時不並行，會卡住其他功能

**類型：** 調查（未來處理，架構級）

### 問題
使用者回報：執行 `/指令` 或 `@mention` Agent 時「好像不會並行，會卡住其他所有功能」——一個請求處理期間其他被卡住。

### 現況事實（初查，已排除部分嫌疑）
- `agent/bridge.py`：`agy` subprocess 用 `asyncio.create_subprocess_exec` + `await`——**非阻塞，不卡 event loop**。非根源。
- `bot/handlers.py`：`/p` 用 `await fetch_price()`——**async 設計**，非阻塞。
- 根源**尚未確認**，剩餘嫌疑：
  1. 某工具內部**同步阻塞呼叫**（`requests` 而非 httpx、`time.sleep`）卡 event loop。
  2. `draw_kchart` 的 **matplotlib 畫圖 CPU 阻塞**（未包 executor）。
  3. **python-telegram-bot 的 `concurrent_updates` 設定**（預設可能序列處理 update）。
  4. `agy` 單一 Agent 進程很慢 / 全域鎖。
  5. 跨請求**共享鎖 / 全域狀態**（UAnalyze 登入、快取寫檔）序列化。

### 待辦（未來）
- [ ] 用真實並發請求復現，確認哪種組合會卡。
- [ ] 逐工具 grep `requests.` / `time.sleep` / 同步 IO，改 async 或包 `asyncio.to_thread`。
- [ ] 檢查 `Application` 的 `concurrent_updates` 設定。
- [ ] matplotlib 畫圖移到 executor thread。
- [ ] UAnalyze 登入/token 並發安全化。

### 引入實作中的即時注意（重要）
本次引入的重功能（逐字稿16K、DCF、`/data` 多 API）會**放大**此問題。實作紀律：
- 一律用 **async httpx**，**絕不從來源 uanalyze_cli 移植同步 `requests`**（來源整包是 requests，移植時必須改 async）。
- DCF 純計算若 CPU 較重，考慮 `asyncio.to_thread`。
- UAnalyzeAuth（ticket 01）login/token 設計須並發安全（多請求同時觸發登入不互卡）。
- 目標：新功能**不惡化**並發問題；根治留待本 INV-02 專門處理。
