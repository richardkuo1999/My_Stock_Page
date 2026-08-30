# 08 — 新聞聚合新增第 16 來源：UAnalyze 專欄

**What to build:** `tools/fetch_news.py` 新增一個來源「UAnalyze 專欄」（`api.uanalyze.com.tw/data/fetch/column/search`，跨產業專欄，total≈2369）。`/news` 選單多此來源選項，回專欄文章列表（標題 + 日期）。無公開 permalink（付費內容，使用者自用），`url` 留空或指 pro 首頁。全文 on-demand 屬獨立 backlog，本張不含。

**Blocked by:** 01（走 JWT）。

**Status:** DONE

- [x] `/news` 選單多「UAnalyze 專欄」來源；選它回列表（title + created_at，summary 由 content 去 HTML 截斷）
- [x] 端點用斜線 `data/fetch/column/search`（非底線）；分頁用 meta
- [x] 純資料不呼叫 AI
- [x] Agent 支援：`fetch_news` 自動含此來源（工具 3 已在 prompt）；`agent/prompts.py` 視需要註記新來源
- [x] 文件同步：README（新聞來源 15→16）、ARCHITECTURE、`HELP_TEXT`（若涉及）、map/ticket 狀態
- [x] `tests/test_fetch_news.py` 新增此來源解析測試；全套測試綠
