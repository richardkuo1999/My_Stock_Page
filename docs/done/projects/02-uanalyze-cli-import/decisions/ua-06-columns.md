# A11 獨家專欄文章庫 是否引入與形態

<!-- labels: wayfinder:grilling -->
<!-- parent: map-uanalyze-cli -->

**Type:** grilling (HITL)
**Status:** ✅ closed（2026-08-23，assignee: agent）

## Resolution — A11 專欄文章庫

- **引入 A11**，形態 = **併入現有新聞聚合（`fetch_news`）當新來源**（第 16 個來源，如 name「UAnalyze專欄」）。與現有第 5 來源 `UAnalyze`（`uanalyze.com.tw/articles`）**不重疊**（使用者確認）；與 `report-summaries`（個股研報摘要）也不同批——這批是**跨產業專欄長文**（DailyIssue 每日議題）。
- **全文走 on-demand**：新聞列表顯示 title + created_at + tag；使用者**點某篇才輸出全文**（`content` 欄位）。此全文機制已另計獨立 backlog：`docs/todo/backlog/news-fulltext-on-demand.md`（跨全來源，非本 map 範圍）。
- **版權**：內容為 UAnalyze **付費訂閱**專欄。使用者確認**自用**（自己看，不對外散布），版權疑慮在自用範圍可接受。

## API 事實（實測確認，2026-08-23）

**端點存活**（research 曾誤判已死，實為 `data_fetch` vs `data/fetch` 斜線筆誤，已更正 `research/ua-columns/findings.md`）：
```
GET https://api.uanalyze.com.tw/data/fetch/column/search?Keywords=&page=1&per_page=N
Header: Authorization: Bearer <access_token>（JWT，A 套認證）, Origin/Referer: https://pro.uanalyze.com.tw
```
- 回 `data.columns[]` + `data.meta{current_page, per_page, total=2369, last_page=474, has_next}`（分頁完整）
- item 欄位：`id / title / tag(DailyIssue…) / content(全文 HTML) / create_id / top / created_at / image`
- **列表直接帶 `content` 全文**；帶 `&id=<n>` 回單篇。
- 認證 = **A 套 JWT**（與現有 `tools/uanalyze.py` 同，複用 `UAnalyzeAuth` jwt helper，ua-02）。

## 待實作接口（給 spec）

- `tools/fetch_news.py`：新增一個 source（`type: "uanalyze_column"`），打 `data/fetch/column/search` 拿列表 → 產出 `{title, source:"UAnalyze專欄", date:created_at, url:(空或指 pro 首頁), summary:(可由 content 去 HTML 標籤截斷)}`。純資料不呼叫 AI。
- 全文 on-demand：見 `news-fulltext-on-demand.md`；此來源全文取法 = 同端點帶 `id` 拿 `content`（HTML→純文字）。
- ⚠️ item **無公開 permalink**（付費內容），`url` 欄位留空或指 `pro.uanalyze.com.tw`。

## Question

決定 A11 是否引入、及形態：

- **A11 獨家專欄文章庫閱讀器** — `option_standalone_read_articles`；介接 `api.uanalyze.com.tw/data_fetch/column/search`，2,323+ 篇付費專欄；含 `format_article_content` HTML 排版轉換
- 認證：需釐清用哪套（可能又是另一組 domain，見認證調查）

**與現有的張力：**
- 這是「文章庫」性質，與現有 15 來源新聞（`fetch_news`）可能整合——變成第 16 個新聞來源？還是獨立指令？
- 付費專欄內容推播的合理性（版權/份量）
- 分頁閱讀（N/P 翻頁）形態在 Telegram 怎麼呈現

**注意：** 此 ticket 認證域可能與 ua-01 調查範圍不同（`api.uanalyze.com.tw` vs `data_fetch` domain），resolve 時可能需補查。

**來源檔案：** `uanalyze_cli/uanalyze_cli.py` line 109（format_article_content）、line 774（read_articles）
