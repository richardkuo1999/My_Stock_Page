# 群2：法說會逐字稿 / AI 15 主題 是否引入與形態

<!-- labels: wayfinder:grilling -->
<!-- parent: map-uanalyze-cli -->
<!-- blocked-by: ua-02-auth-decision -->

**Type:** grilling (HITL)
**Status:** ✅ closed（2026-08-22，assignee: agent）

## ✅ 逐字稿疑點已解（2026-08-23，使用者提供 Network URL）— A1 升級為「真逐字稿全文」

**謎底：真正的逐字稿全文端點一直存在，來源 CLI 漏用了。** 使用者直覺（「逐字稿 API 用錯」）正確。

**真逐字稿取法（實測確認，兩步）：**
1. **清單** — `GET gidp.uanalyze.com.tw/data_fetch/api/WebStockInfo/{ticker}?country=TW`（GIDP token，C 套）→ `data.data` 裡 `ChineseAccount=="逐字稿"`（key `ua80305_cp`）的 `Data` 是 list，每筆 `{Data:"2026/07/16", id:"202607162330"}`（id = 日期+股號）。2330 實測 **12 筆**（歷次法說）。
2. **全文** — `GET cronjob.uanalyze.com.tw/data_fetch/api/TranscriptDetail?id={id}&country=TWN`（**B 套 4-cookie session + Origin/Referer**；注意 `country=TWN` 非 TW）→ `data.data` 含：
   - `transcript`（**全文逐字稿**，實測 2330 Q2 約 16K 字，含分段小標與 markdown 表格）
   - `title`（AI 濃縮標題）、`stock`、`date`
   - `pdf`（`cronjob.../data_fetch/pdf/2330_20260716`，需 cookie）、`en_pdf`（TWSE mopsov 公開英文 PDF）、`video`（.mp4 路徑）

**來源 CLI 的 bug：** `get_stock_basic_info`（uanalyze_cli.py:157-176）從 WebStockInfo 拿到逐字稿 id **卻沒用**，只拿 date 去 filter report-summaries + 打 completions。真全文端點被漏用，功能名不副實。

### A1 升級決策（取代原「只給摘要」）

- **A1 = 引入真逐字稿全文**，仍併進 `/ua <代號>` 選單：選「法說會逐字稿」→ 列日期（12 筆，來自 WebStockInfo）→ 選一篇 → 打 TranscriptDetail 拿全文。純資料不呼叫 AI（transcript 是現成文字）。
- **全文分頁形態（使用者裁決）**：全文約 16K 字 > Telegram 4096 上限 → **分頁 + 上一頁/下一頁按鈕**。
  - **做法 2（抓一次+快取翻頁）**：選某篇 → **打一次** TranscriptDetail 拿全文 → **存記憶體快取** → 翻頁用 `edit_message` 換頁碼、只讀快取切段落，**翻頁不再打 API**（解決「一直送 API」的顧慮）。
  - **快取 = 記憶體 + TTL**（比照 news_cache 精神，不落檔；過期或重啟後再抓一次）。
- **PDF 連結注意**：`pdf` 欄需 cookie 認證才能開，非公開連結；實作若要附連結需驗證可達性（或改推 `en_pdf` 公開版）。

**認證**：逐字稿橫跨 **C（WebStockInfo 清單）+ B（TranscriptDetail 全文）**，皆 ua-02 的 `UAnalyzeAuth` 已涵蓋（gidp helper + cookie helper）。

**findings 待補**：可另存 `research/ua-transcript/` 記此兩步端點（目前記於本 ticket 已足夠給 spec）。

---

## Resolution — 群2：A1 引入、A2 不引入

**比對事實：** A2（15 主題）與 A1 都打 `data.uanalyze.twobitto.com`（JWT）。A2 的 15 主題**幾乎全被現有 `/ua` 的 32 面向涵蓋**（32 是 15 的超集）。A1 打 `/api/report-summaries?stock=X`（研報摘要），是現有沒有的「個股 × 日期」維度。

- **A2（15 主題 AI 分析）= 不引入**。理由：現有 `/ua` 32 面向已涵蓋，硬搬只是重複維護兩份 prompt 清單、零增量。
- **A1（法說會/研報摘要）= 併進現有 `/ua` 選單**，形態：
  - `/ua <代號>` 面向選單**多一個選項**（如「法說會逐字稿 / 研報摘要」）
  - 選它 → **再跳一層選日期**（動態：打 `report-summaries?stock=X` 取該股實際有的日期/篇）
  - 選日期 → 回該篇 `report-summaries` 的 `summary`
  - **純資料、不呼叫 AI**（實測 `summary` 欄本身自足：首行標題+內文，如 2330「英特爾EMIB崛起…」119字），符合架構鐵則。使用者想要 AI 觀點可另走 `@mention`。

**resolve 時發現：** 真實 `report-summaries?stock=X` 回的不是「一場法說=一日期」，而是**該股最近 N 篇研報摘要（多日期、多 question_type）**。→ 第二層選單語意實為「選一篇研報摘要」，非嚴格「法說會場次」。實作 ticket 需照此設計選單文案。

**待實作接口（給 spec）：** `tools/uanalyze.py` 新增純資料函式（如 `list_stock_reports(stock)` 回 [{date, question_type, summary}]），`bot/handlers.py` 的 `/ua` callback 加第三層日期選單分支。

## ⚠️ 未解事實缺口（實作前必查）—— ✅ 已於 2026-08-23 解決（見本 ticket 頂端「逐字稿疑點已解」）

> 以下為當初記錄的疑點，已查證：真逐字稿端點 = `cronjob.../TranscriptDetail?id=&country=TWN`（B 套 cookie），來源 CLI 漏用。保留原文供歷史參考。

**「逐字稿」的 API 可能用錯了。** 來源 `option_transcript_by_date`（uanalyze_cli.py:179-265）名為「法說會逐字稿」，但實際只打兩個端點：
1. `GET data.uanalyze.twobitto.com/api/report-summaries?limit=15&offset=0&stock={ticker}`（uanalyze_cli.py:210）— 摘要，非逐字稿全文
2. `GET data.uanalyze.twobitto.com/completions?prompt=觀察重點&stock={ticker}`（uanalyze_cli.py:229）— AI 觀點（我方已決定不取）

**兩個都不是真正的「逐字稿全文」端點。** 疑問：UAnalyze 是否另有一個真正的法說會逐字稿 API（來源作者可能用錯/取巧）？

**行動：** 實作此功能前，需重新查清楚 UAnalyze 是否有真逐字稿端點。若有 → 選單那個選項該接真逐字稿；若無 → 該選項語意應正名為「研報摘要」而非「逐字稿」。**目前已定的決策（回 report-summaries 摘要、純資料）不變，但選單命名與是否接真逐字稿待查證後定案。**

## Question

決定這兩個 JWT completions 類功能是否引入、及引入後形態（Telegram 指令 / Agent 工具 / 不引入）：

- **A1 法說會逐字稿重點摘要**（依日期選擇）— `option_transcript_by_date`
- **A2 法說會/個股產業 AI 分析（15 大主題）** — `option_ai_completions`；注意這與現有 `/ua` 的 32 面向可能重疊，需釐清差異

**與現有的張力：** A2 的「15 大主題」vs 現有 `/ua` 的 32 面向——是取代、合併、還是各自獨立？A1 逐字稿摘要來源若是 AI completion，工具本身不能呼叫 AI（架構鐵則）——需決定是純抓逐字稿（工具）還是走 Agent 摘要。

**來源檔案：** `uanalyze_cli/uanalyze_cli.py` line 179（transcript）、line 268（ai_completions）
