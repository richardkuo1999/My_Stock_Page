# 新聞全文 on-demand 抓取（跨全來源）

<!-- labels: backlog, spec -->

<!-- 獨立主題：不屬 uanalyze_cli 引入 map，另行規劃 -->

> **2026-09-06 完成結論（移入 done/）**
>
> 需求收斂：全文的目的是**讓 Agent 分析公司時讀得到完整內文**，
> **不做**「使用者在 Telegram 點按鈕讀全文」——使用者自己點原文連結即可。
>
> **已交付：** `tools/fetch_news.py` 新增 `fetch_fulltext(url)` + CLI `--fulltext <URL>`：
> - on-demand 單篇抓取（有需要才抓某一篇，不預抓）。
> - BeautifulSoup 啟發式抽正文（`_extract_main_text`：去 nav/footer/script，優先
>   `<article>`，否則最大段落區塊），`verify=False` 相容 TW 來源 SSL。
> - 單篇全文 cache `data/news_fulltext_cache.json`（TTL 24h），重讀免重抓。
> - 抓不到正文（付費牆 / JS 動態頁 / 過短）→ 回 `{"error": ...}`，呼叫端退回摘要+連結
>   （即被動的付費牆策略，不需另建逐來源政策表）。
> - 上限 12000 字（`truncated` 標記）。
> - 頂部 docstring 改寫成「summary 只是摘要、要深入分析先列新聞拿 url 再 --fulltext 讀全文」，
>   Agent `head -30` 即可發現用法；`agent/prompts.py` 工具清單也補上該行。
> - 新增 5 個單元測試（抽取/cache 命中/短內文 error/無效 URL/長文截斷），全套件通過。
>
> **決定不做（需求已排除）：**
> - NF-01 使用者按鈕讀全文（Telegram UI）—— 使用者點連結即可，不需要。
> - NF-03 逐來源政策表 —— 被動 error 退回已足夠。
> - NF-04 逐來源精修解析 —— Phase 1 泛用抽取已滿足 Agent 分析需求，未見必要。

## 來源

使用者 2026-08-23 於 uanalyze_cli map（ua-06）討論中提出的**新需求**，與 A11 專欄引入相關但性質不同，故拆出獨立待辦。

## 需求

現況：`/news` 選來源後，每篇只輸出 `{title, source, date, url, summary}` — **只有摘要，無全文**（`tools/fetch_news.py`，15 來源，`_make_article` 產出）。

想要：`/news` 選單選了某來源、列出文章後，**使用者點某篇 → 才去抓「那一篇」的全文並輸出**。

**關鍵設計 = lazy / on-demand：**
- **有人點某篇才抓那篇全文；沒人點就不抓。**
- 避免「15 來源全部預抓全文」的工程量與版權炸彈；變成單篇、按需。

---

## 實作 spec（2026-09-06 規劃，讀過現況程式碼後）

### 現況事實（已核對程式碼）

- `/news` 流程在 **`bot/subscriptions.py`**：`news_now_handler`（出選單）→ `news_source_callback`（`callback_data=news:all` / `news:<i>` / `news:back`）。
- `news_source_callback` 目前把整批文章**丟給 Agent 摘要成一則文字**（`edit_message_text`），**沒有逐篇結構、也沒有逐篇按鈕**。fallback 是 `• [來源] 標題\n └ URL` 條列。
- 文章池來自 `tools/fetch_news.py::latest()`，**已有 disk cache**：`data/news_cache.json`，結構 `{fetched_at, articles:[{title,source,date,url,summary}]}`，TTL `CACHE_TTL_SECONDS=600`（10 分鐘）。
- `_make_article`（L104）產出的 article dict 目前**無全文欄位**。
- `handlers.py` 已有 4096 字元分段送訊息的既有 pattern（`/ask` text 回覆），可重用於長全文。

### 核心設計決策

**1. 文章識別（callback_data 限制）**
Telegram `callback_data` 上限 **64 bytes**，塞不下 URL。作法：全文按鈕帶
**來源 index + 文章 index**（對應該次 `latest()` 快取內的位置），例
`callback_data="newsfull:<src_i>:<art_i>"`。回呼時重新 `await latest()`（10 分鐘內走
快取、同一份清單，index 穩定）取回該篇 `url`，再抓全文。
> 風險：使用者點按時已超過 10 分鐘 → 快取刷新、index 可能位移。緩解：cache 內容變動
> 不頻繁（同來源順序穩定）；若抓到的 title 與按鈕不符可接受（極少）。或改存
> 「該次列表的 url 清單」到 `context.user_data`（per-user，記憶體），index 對這份私有清單。
> **建議採後者（user_data 私有清單）**：不受全域 cache 刷新影響，最穩。

**2. 逐來源全文抓法（type 分派延伸）**
`fetch_news.py` 已有 `type` 分派（rss/json/udn/uanalyze/…）。新增
`async def fetch_full_text(url, source_type) -> dict`，依 `source_type` 分派到逐來源
內文解析器。**分階段交付，不必一次做完 15 來源**：
- **Phase 1（泛用後援）**：通用 HTML 抽取（`readability-lxml` 或 BeautifulSoup 取
  `<article>`/最大文字塊），涵蓋多數 RSS/HTML 來源。抓不到就回 fallback（見下）。
- **Phase 2（逐來源精修）**：對 Phase 1 效果差的來源寫專用解析（CNYES json 內文 API、
  UDN、Fugle blog、Forecastock 等）。

**3. 版權 / 付費牆政策（逐來源）**
分三類，存成一張表（來源 → 政策）：
- `full`：可抓可推全文（多數公開 RSS/新聞）。
- `link_only`：付費牆 / 版權敏感 → **不抓全文，只回標題 + 摘要 + 原文連結**
  （Vocus 特定作者、UAnalyze 付費專欄、Pocket 學堂等，實作時逐一確認）。
- `summary_only`：只推現有 summary。
> 預設保守：未知來源先歸 `link_only`，確認可全文後再放行。

**4. Telegram 長文呈現**
全文可能超過 4096 → 重用既有分段送 pattern（多則 message）。過長（如 > N 則）時
截斷並附「繼續讀原文」連結。圖片/表格不處理（純文字）。

**5. 單篇全文快取**
新增 `data/news_fulltext_cache.json`：`{ url_hash: {text, fetched_at} }`，TTL 建議
6~24 小時（新聞內文不變）。抓過的單篇直接回快取，避免同篇重複抓。沿用
`fetch_news.py` 既有 `_read_/_write_` cache 寫法。

### 交付切分（建議 ticket）

- **NF-01**：`/news` 列表改為**逐篇結構 + 每篇「📄 讀全文」按鈕**（先只帶
  index、點了先回原文連結，不抓全文）——驗證按鈕/回呼/user_data index 機制。
- **NF-02**：`fetch_full_text` + Phase 1 泛用 HTML 抽取 + 單篇 cache + 長文分段送。
- **NF-03**：逐來源政策表（full/link_only/summary_only）+ paywall 來源導連結。
- **NF-04**：Phase 2 逐來源精修解析（依 NF-02 實測效果差的來源）。
- 每張附測試（mock 內文頁 HTML → 斷言抽取結果 / 政策分類 / 分段）。

### 待確認（實作前問使用者）

- 文章識別採 **user_data 私有清單**（建議）還是全域 cache index？
- Phase 1 是否可引入 `readability-lxml` 依賴（否則純 BeautifulSoup 啟發式）？
- paywall 來源的預設：`link_only` 保守是否 OK？

## 範圍界定

- **不屬** uanalyze_cli 引入 map（那張只處理引入外部工具功能）。
- 這是對**現有 `/news` / `fetch_news`** 的功能增強，跨全部 15（+A11=16）來源。
