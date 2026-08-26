# 資料顯示優化：善用表格（Agent 與 /command 皆是）

<!-- labels: backlog, ux, done -->
<!-- 獨立主題：對現有呈現層的 UX 增強，另行規劃 -->

**Status:** done（2026-08-26）

## 完成摘要

採「等寬對齊文字表格 + Markdown ```code block```」路線（未走圖片表格，故不依賴 INV-02）：

- `bot/tables.py` — 共用 helper：`render_table()`（依 `east_asian_width` 把中文算 2 格寬對齊；標籤欄靠左、數字欄靠右）+ `code_block()`（fence 包裝、防三重反引號逃逸）。
- `bot/handlers.py` — `/data` 五個 `_format_*` 全改用表格；`data_callback` 送出時 `code_block()` + `parse_mode="Markdown"`（財務指標採「指標為列 × 年份為欄」避免爆寬）。
- `agent/prompts.py` — `SYSTEM_PROMPT` 加入「多維數據用等寬表格並包在 code block」輸出指示 + 範例（`@mention` 端）。
- `tests/test_tables.py` — 新增 20 測試；全套 **344 passed**。樣式已推 admin chat 目視、`@mention` 分析南茂整條 pipeline 實測成功。
- 架構鐵則維持：工具仍回純資料摘要 JSON，不呼叫 AI；表格化只在呈現層。

> 後續（未列入本 ticket，需要時另開）：Agent 偶爾繞路 `find_by_name`/`list_dir` 找檔案；`@mention` 表格化為軟性 prompt 引導，力道待觀察。

## 來源

使用者 2026-08-23（uanalyze_cli 引入 8 張 ticket 完成後）提出的顯示優化需求。

## 需求

現況：多數資料呈現是「逐行中文文字」（`bot/handlers.py` 的 `_format_consensus` / `_format_pershare` / `_format_supply` / `_format_order` / `_format_dcf` 等），多維/多年份資料（如財務指標近 5 年 × 多指標、法人共識多期）用「、」串接，**可讀性有限**。

想要：善用**表格**呈現，讓多維資料更好讀——**Bot `/command` 與 Agent `@mention` 兩邊都要**。

## 待規劃內容（規劃時處理）

- **Telegram 端表格的技術選項**（規劃時評估取捨）：
  - Markdown 表格（Telegram 對 table 支援有限，`parse_mode=Markdown/MarkdownV2` 不渲染真表格）→ 可能不可行或顯示為原始文字。
  - **等寬對齊文字表格**（用 monospace ```code block``` 包住 + 空白對齊欄位）→ 手機可讀性佳，最務實。
  - 圖片表格（matplotlib 畫成圖片，比照 `/k`）→ 好看但重、且 matplotlib 已知有並發阻塞疑慮（見 INV-02）。
  - 拆分多則訊息 / 摺疊。
- **對象範圍（兩邊都要）**：
  - `/command` 呈現層：`/data` 五類（尤其財務指標的年份 × 指標矩陣、法人共識多期）、`/p` 基本面、逐字稿等的 `_format_*` 函式。
  - **Agent 輸出**：`@mention` 回覆的資料若含多維數據，也應以表格化/結構化呈現（可能需在 `SYSTEM_PROMPT` 指示 Agent 用等寬表格輸出，或工具回傳結構讓 Agent 好組表）。
- **架構鐵則不變**：工具仍回**純資料摘要 JSON**（不呼叫 AI）；表格化是**呈現層**的事（bot handlers 格式化函式 / Agent 輸出風格），不污染工具。
- **一致性**：兩邊表格風格盡量一致（同一套等寬表格 helper 可共用）。
- **邊界**：Telegram 4096 字上限 + 手機窄螢幕，寬表格需截欄/換行策略（財務指標近 5 年 × 10 指標很容易爆寬）。

## 範圍界定

- 對象是**呈現層**：`bot/handlers.py` 的 `_format_*` 函式群 + Agent 輸出風格（`agent/prompts.py`）。
- **不動工具的純資料 JSON 契約**（工具照回摘要，表格化在外層）。
- 建議先做一個共用「等寬文字表格 helper」，再逐一套用到 `/data` 各 `_format_*`，Agent 端在 `SYSTEM_PROMPT` 加輸出指示。
- 與 INV-02（matplotlib 並發阻塞）相關：若選圖片表格路線需先解 INV-02。
