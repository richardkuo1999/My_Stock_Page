# Spec：引入 uanalyze_cli 功能到 Stock Bot

<!-- labels: ready-for-agent -->
<!-- source: map.md（8 張 wayfinder ticket 全 closed）-->

## Problem Statement

使用者手上有一個外部工具箱 `stocktool/uanalyze_cli`（UAnalyze 終端），提供 12 項台股分析功能（法說會逐字稿、法人共識、財務指標、DCF 估值、供應鏈、訂單能見度、專欄文章庫、全台股名對照…）。這些功能目前只能在那支獨立 CLI 用，沒有整合進使用者日常在用的 Telegram Stock Bot。使用者想把「有價值、且適合 Telegram 形態」的功能引入 Bot，並解決 UAnalyze 三套並存認證的統一問題。

## Solution

在維持現有架構鐵則（Bot 薄殼 + 純確定性工具不呼叫 AI + Agent 協調智能步驟）的前提下，逐一評估 A1–A12，把適合的功能以正確形態引入：

- 新增快捷指令 **`/data <代號>`**（仿 `/ua` 的選單模式），內含 4 項 data_fetch 分析 + DCF 估值。
- **`/ua`** 選單新增「法說會逐字稿」選項，接**真逐字稿全文**（分頁閱讀）。
- **`/p`** 疊加 UAnalyze 基本面指標（best-effort，不拖累秒回）。
- 新聞聚合新增第 16 來源「UAnalyze 專欄」。
- 用 UAnalyze 官方全台股名對照表（12,361 檔）**取代**現有 seed-20 自成長機制。
- 三套認證統一為單一 `UAnalyzeAuth`（一次登入 → 三個 helper）。

批次 CSV、AI 15 主題、河流圖、各券商 EPS 明細等**不引入**（理由見 Implementation Decisions）。

## User Stories

1. 作為 Bot 使用者，我想用 `/data 2330` 叫出一個選單，選擇要看哪個進階分析面向，這樣我不必記多個指令。
2. 作為使用者，我想在 `/data` 選單看「法人共識」（單季 EPS 實際 vs 法人預估、月營收/年營收共識），以便判斷法人對該股的獲利預期。
3. 作為使用者，我想在 `/data` 選單看「財務指標」（每股自由現金流、EPS、EBITDA、ROE、ROIC、股利等近 4–5 年趨勢），以便快速評估基本面。
4. 作為使用者，我想在 `/data` 選單看「供應鏈」（同業/供應鏈對照標的），以便延伸研究相關個股。
5. 作為使用者，我想在 `/data` 選單看「訂單能見度」（訂單能見度 + 合約負債），且當該股無此資料時得到清楚的「查無資料」提示，而不是空白或錯誤。
6. 作為使用者，我想在 `/data` 選單看「DCF 估值」（每股合理內在價值、1 年後前瞻價值、營收動能），以便有一個估值錨點。
7. 作為使用者，我想在 `/ua 2330` 的面向選單多一個「法說會逐字稿」選項，以便讀該股法說會內容。
8. 作為使用者，選「法說會逐字稿」後我想看到該股歷次法說會的日期清單，以便選我要讀的那一場。
9. 作為使用者，選定某場逐字稿後我想讀到**完整逐字稿全文**（非只有摘要），以便掌握管理層原話。
10. 作為使用者，逐字稿全文很長時我想用「上一頁 / 下一頁」按鈕分頁閱讀，而不是被一次灌爆或洗版。
11. 作為使用者，我翻頁時希望是秒回、且不要讓 Bot 一直重打 UAnalyze API，以免慢又浪費。
12. 作為使用者，我用 `/p 2330` 查即時股價時，希望除了價量還能附上基本面指標（本益比、殖利率等），讓一則訊息資訊更完整。
13. 作為使用者，我希望即使 UAnalyze 基本面暫時抓不到，`/p` 的即時價量仍照常秒回，不被拖累。
14. 作為使用者，我想在 `/news` 選單多一個「UAnalyze 專欄」來源，讀到 UAnalyze 的跨產業專欄文章列表（標題+日期）。
15. 作為使用者，我點某篇 UAnalyze 專欄時，才去抓該篇全文（on-demand），沒點的就不抓。
16. 作為使用者，我查任何個股代號（`/p`、`/ua`、`/data`、個股新聞過濾）時，希望公司名對照涵蓋幾乎全台股，而不是只有少數幾檔命中。
17. 作為維運者，我希望股名對照表能定期自動刷新，保持與市場同步（新上市櫃股票也能命中）。
18. 作為維運者，萬一官方對照表缺某檔，我仍想能手動補一筆（`--set` 後備）。
19. 作為開發者，我希望 UAnalyze 的三套認證（JWT / cookie / GIDP）收斂成單一入口，一次登入即可打三種 domain，降低維護成本。
20. 作為開發者，我希望所有新工具都維持「純確定性、不呼叫 AI」，符合現有架構鐵則。
21. 作為使用者，我在 `/help` 看到的指令說明，永遠與實際可用指令一致（不再漏列）。

## Implementation Decisions

### 認證（ua-01 / ua-02 / ua-08）
- 三套認證並存，無法收斂成一套，但**只需登入一次**：實測 A 套 JWT 與 B 套 cookie 的 access_token byte-for-byte 相同。
- 於 `tools/uanalyze.py` 擴充**單一 `UAnalyzeAuth`**：一次 login → 三個 helper：
  - **jwt helper**（A 套）：`Authorization: Bearer <access_token>`，用於 `api.uanalyze.com.tw` / `data.uanalyze.twobitto.com`。
  - **cookie helper**（B 套）：記憶體組 4-cookie（access_token/refresh_token/token_type/expires_in）+ header `Origin/Referer: https://pro.uanalyze.com.tw`，用於 `cronjob.uanalyze.com.tw`。**不移植 CLI 的 cookie 檔**。
  - **gidp helper**（C 套）：`Authorization: Bearer <寫死公開 GIDP token>` + query `country=TW`，用於 `gidp.uanalyze.com.tw`。GIDP token 當模組常數並註解來源。

### `/data <代號>` 選單（ua-04 + ua-05）
- 新增指令 `/data`，仿 `/ua` 的 inline 選單模式，5 個選項：
  1. **法人共識**（A3）：跨 domain — 單季 EPS 追蹤走 cronjob `EPSTrackingActualVSForecastModule`；月/年營收共識走 gidp `MonthlyRevenueTrackingConcensuslModule` / `EPSRevenueConsensusEstimate`。
  2. **財務指標**（A4，標籤刻意命名「財務指標」非「估值」）：cronjob `PerShareValueForValuationModel`。10 項每股指標 × 多年，**只顯示近 4–5 年**。
  3. **供應鏈**（A7）：cronjob `StockComparisonStockPool`（同業代號清單）。
  4. **訂單能見度**（A8）：cronjob `OrderVisibilityModule` + `ContractLiabilityModule`。**無資料時回「查無訂單能見度資料」**。
  5. **DCF 估值**（A5）：走 `only_dcf` 等價的純計算路徑，**不呼叫 AI**。純計算（WACC、時間權重、roll-forward `V1=V0*(1+WACC)-EPS`）可原樣移入。回關鍵數字：每股合理內在價值、1 年後前瞻價值、營收動能、時間加權基期。
- data_fetch 回傳是「圖表用多維 series」→ 需濃縮成 Telegram 可讀文字，非直接倒 JSON。

### `/ua` 逐字稿（ua-03，逐字稿疑點已解）
- `/ua` 面向選單新增「法說會逐字稿」。真逐字稿取法**兩步**：
  1. **清單**：gidp `WebStockInfo/{ticker}?country=TW` → `data.data` 內 `ChineseAccount=="逐字稿"`（key `ua80305_cp`）的 `Data` list，每筆 `{Data: 日期, id: 日期+股號}`。
  2. **全文**：cronjob `TranscriptDetail?id={id}&country=TWN`（注意 `TWN`）→ `data.data.transcript` 全文（實測約 16K 字，含分段小標與 markdown 表格）+ `title`/`pdf`/`en_pdf`/`video`。
- 選項流程：選「逐字稿」→ 列日期清單 → 選一場 → 顯示全文。
- **全文分頁（做法 2：抓一次 + 快取翻頁）**：選定某場 → 打一次 TranscriptDetail 取全文 → 存**記憶體快取（附 TTL）** → 「上一頁/下一頁」按鈕用 `edit_message` 換頁碼、只從快取切段落顯示，**翻頁不再打 API**。快取過期或重啟後再抓一次。
- 純資料不呼叫 AI（transcript 是現成文字）。PDF 連結需 cookie，非公開；若附連結需驗證可達性或改用 `en_pdf` 公開版。
- **A2（AI 15 主題）不引入**：現有 `/ua` 32 面向為超集，零增量。

### `/p` 疊加基本面（ua-04 A9）
- `/p` 保留現有 Fugle/FinMind 價量（秒回），**再 best-effort 補打** gidp `WebStockInfo` 取基本面指標（本益比/殖利率等）附上；UAnalyze 逾時/失敗則**略過，不影響 `/p`**（形態 a1）。
- 查證：現有 `/p` 只回 price/change/change_pct/volume，無基本面 → A9 是真增量、不重複。

### 新聞第 16 來源：UAnalyze 專欄（ua-06）
- `tools/fetch_news.py` 新增來源（`type: "uanalyze_column"`）：`GET api.uanalyze.com.tw/data/fetch/column/search?Keywords=&page=&per_page=`（**斜線 `data/fetch`，非底線**；JWT + Origin/Referer）。回 `data.columns[]` + `data.meta{total, last_page, has_next}`（total≈2369）。
- 列表 item：`id/title/tag/content(全文HTML)/created_at/image`。產出 `{title, source:"UAnalyze專欄", date:created_at, url:(空或指 pro 首頁), summary:(content 去 HTML 截斷)}`。
- **無公開 permalink**（付費內容）→ `url` 留空或指首頁。內容為付費訂閱，使用者確認**自用**。
- 全文 on-demand 屬**獨立 backlog**（`docs/backlog/news-fulltext-on-demand.md`），非本 spec 範圍；本 spec 只做「列表併入新聞來源」。

### 股名對照表取代（ua-07）
- 新增 `fetch_stock_pool()`（gidp `StockPool?country=TW`，回 12,361 檔 `{stock_code, stock_name}`）。
- `tools/lookup_stock_name.py` 改為：啟動/首次查詢時灌入本地表（`data/stock_names.json` 或記憶體）→ 之後查本地 → **定期刷新（如每週）**。**Agent 自成長主路徑退役**，**保留 `--set` 手動寫回當後備**。
- 介面不變，資料源由 seed-20 換成全表 → `lookup_stock_name` / `fetch_news` 個股過濾自動受益。

### 不引入清單
- A2（AI 15 主題）、A6（河流圖，需自畫圖）、A12 批次 CSV 本體（離線分析，保留獨立 CLI）、`fetch_broker_eps_estimates`（各券商明細，A3 共識已足）。
- A10（研報摘要）已擁有（現有監控推播）。

### ⚠️ 文件同步紀律（貫穿所有 ticket，使用者明確要求）
每完成一個功能，**同一個 commit 內**同步更新以下所有面向，不得延後、不得漏：
1. **`bot/handlers.py` 的 `HELP_TEXT`**（最易漏 — 是程式碼字串，非表格）——已知先前漏了 `sub/unsub_ua_reports`，本 spec 開工前已補。
2. **README.md**：Telegram 指令表、工具 CLI 清單、資料儲存、測試數。
3. **ARCHITECTURE.md**：指令表、scheduler 表。
4. **`.env.example`**（若新增環境變數）、**config.json**（若新增設定）。
5. 對應的 **map / ticket 狀態**。

## Testing Decisions

- **原則**：只測外部行為（給定 mock 的 UAnalyze API 回應 → 函式回傳結構 / Telegram 訊息文案 / 分頁行為正確），不測實作細節。外部 HTTP 一律 mock 隔離（比照現有測試）。
- **沿用現有 seam，零新框架**：
  - `tests/test_uanalyze.py` — 新資料函式（逐字稿清單/全文、data_fetch 模組群、DCF 純計算、StockPool）。DCF `_compute_dcf` 是純函式，直接以「EPS 輸入 → 內在價值輸出」斷言，最好測。
  - `tests/test_fetch_news.py` — UAnalyze 專欄新來源解析與 `_make_article` 產出。
  - `tests/test_lookup_stock_name.py` — StockPool 灌入本地表、查詢命中、`--set` 後備、刷新行為。
  - `tests/test_handlers.py` — `/data` 選單 callback、`/ua` 逐字稿分頁（做法2：抓一次後翻頁不重打 API，用 mock 斷言 API 呼叫次數）、`/p` 基本面 best-effort（UAnalyze 失敗時價量仍回）、`HELP_TEXT` 含所有註冊指令。
- **prior art**：現有 `test_uanalyze.py`（mock httpx 回應 → 斷言欄位映射）、`test_handlers.py`（fake update/context → 斷言 reply 文案與 callback 分支）。

## Out of Scope

- 全文 on-demand 抓取（跨全 15+ 來源）— 獨立 backlog `news-fulltext-on-demand.md`。
- 來源 B `industry_agent`、來源 C `cb_analyzer.py` — 延後（`backlog/deferred-sources.md`）。
- A12 批次 CSV 進 bot、河流圖畫圖、AI 15 主題、各券商 EPS 明細。
- uanalyze_cli 的互動選單框架本身（一律拆成指令/工具）。
- A10 研報摘要監控與新引入的去重整合細節（實作時視情況處理）。

## Further Notes

- 三個關鍵事實由使用者直覺推動查證：逐字稿 API 用錯（真端點 `TranscriptDetail`）、column/search 是「斜線 vs 底線」筆誤（端點仍存活）、`StockPool` 可取代股名表。findings：`research/ua-auth/findings.md`、`research/ua-columns/findings.md`。
- 決策全歷程：`map.md` + `decisions/ua-01..08`。
- 新增介面總覽：`/data <代號>`（5 項選單）、`/ua` 加逐字稿、`/p` 加基本面、新聞第 16 來源、股名表換 12,361 檔全表。
