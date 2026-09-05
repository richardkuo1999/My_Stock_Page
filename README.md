# Stock Bot — 台股投資輔助 Telegram Bot

AI Agent + Telegram 混合架構的台股投資輔助 Bot。Bot 薄殼負責收發訊息與排程推播，`/ask` 交給 Antigravity Agent 決定呼叫哪些工具，工具是一組獨立的 Python script（可 CLI 執行、也可 import）。

完整架構設計見 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 需求

- Python 3.12+
- （選用）Docker + Docker Compose
- （選用）Antigravity CLI（`agy` 指令）— `/ask` 問 Agent 才需要

## 安裝

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 設定

### 環境變數（`.env` — 機密）

複製 `.env.example` 為 `.env` 並填入：

```env
TELEGRAM_BOT_TOKEN=       # 必填。@BotFather 建立 bot 取得
TELEGRAM_ADMIN_CHAT_ID=   # 必填。管理者 chat id，接收排程失敗通知
FINMIND_TOKENS=           # JSON 陣列字串，如 ["token1","token2"]
FUGLE_API_KEY=            # 富果 API 金鑰（股價、K 線）
UANALYZE_EMAIL=           # UAnalyze 帳號
UANALYZE_PASSWORD=        # UAnalyze 密碼
```

### 應用設定（`config.json` — 非機密）

```json
{
  "vocus_users": ["@ieobserve", "@miula", "65ab564cfd897800018a88cc"],
  "uanalyze_keywords": ["AI", "半導體", "ETF"],
  "news_schedule_interval_min": 60,
  "uanalyze_schedule_interval_min": 30,
  "log_audit_interval_min": 1440
}
```

## 啟動

```bash
# 本機開發
python main.py

# Docker 部署
docker compose up -d
```

看到 `Bot started. Polling...` 即上線。

## Telegram 指令

| 指令 | 功能 |
|------|------|
| `/start` / `/help` | 歡迎訊息 / 指令與功能說明 |
| `/sub_news` / `/unsub_news` | 訂閱 / 取消新聞推播（每小時） |
| `/sub_ua_reports` / `/unsub_ua_reports` | 訂閱 / 取消 UAnalyze 新研究報告推播（每 30 分鐘） |
| `/news` | 跳出選單選新聞來源（全部或指定 15 來源之一），再回覆該來源最新新聞 |
| `/p <代號>` | 即時股價（直接跑工具，秒回），並 best-effort 附上 UAnalyze 基本面（本益比/最新財報/月營收等）與**盤中分時走勢折線圖**，例 `/p 2330` |
| `/k <代號> [天數]` | K 線圖（回傳圖片），例 `/k 2330 60` |
| `/ua <代號>` | UAnalyze AI 分析：跳出選單選分析面向（近況/產業/資本支出…），另含「法說會逐字稿」入口（列歷次法說會→選一場→分頁閱讀完整逐字稿全文，翻頁走記憶體快取不重打 API），例 `/ua 2330` |
| `/data <代號>` | 跳出選單選資料類型（法人共識 / 財務指標 / 供應鏈 / 訂單能見度 / DCF 估值），回濃縮數據，例 `/data 2330` |
| `/ask <問題>` | 自然語言問 Agent（群組、私訊皆可），交給 Agent 決定呼叫哪些工具，例 `/ask 台積電最近怎麼樣`（需先設定 Antigravity CLI，見下） |

> 快捷指令（`/p` `/k` `/ua` `/news`）直接呼叫工具、不經 AI，回應快且省 token；
> 需要組合多個工具或自然語言提問時才用 `/ask`。排程推播只發給訂閱者且會去重。

## Agent（`/ask`）

`/ask 你的問題` 時，Bot 透過 `AntigravityCLIBridge` 呼叫 `agy -p "..." --output-format stream-json`。
需先在本機安裝並登入 Antigravity CLI（`agy` 指令）。未安裝時 `/ask` 會回覆錯誤訊息，其餘功能不受影響。
`/ask` 群組與私訊都適用，不需 `@mention`；空 `/ask`（未帶問題）會回用法提示、不呼叫 Agent。

每次 `/ask` 會由 `agent/prompts.py` 的 `build_mention_prompt()` 組合 system prompt
（角色=台股助理 + 工具清單 + 執行流程）再送給 Agent，Agent 據此決定要跑哪些工具。

**回覆格式由 Agent 自選**：Agent 可在回覆第一行放一個 `FORMAT:` 標記，決定呈現方式，
由 `bot/handlers.py` 的 `_send_agent_reply()` 依標記路由：

| 標記 | 呈現 | 適用 |
|------|------|------|
| `FORMAT: text`（或不放標記） | 純文字 Telegram 訊息（超過 4096 字元自動分段多則送） | 簡短回答、口語說明 |
| `FORMAT: html` | 產生 **`.html` 檔案**當附件傳（`reply_document`），套用內嵌 CSS（表格框線／手機 responsive／深色模式） | 有標題、表格的完整分析報告 |
| `FORMAT: markdown` | 產生 **`.md` 檔案**當附件傳 | 偏文字、條列、Markdown 表格的報告 |

檔案模式（html/markdown）沒有訊息長度上限，適合多面向的完整報告；標記解析在
`bot/reply_format.py`、檔案內容產生在 `bot/reply_docs.py`。檔案送出若失敗會自動退回
純文字分段送，確保使用者一定收得到內容。

> ⚠️ **搜尋範圍限制（已實作）**：bridge 呼叫 `agy` 時加 `--sandbox --add-dir <REPO_ROOT>`，
> 把 Agent 關在專案 workspace 內——可正常執行 `tools/*.py`，但無法 `find` / 讀取專案目錄
> 以外的檔案（實測：專案外存取回「被限制」）。這解決了先前 Agent 會掃整台電腦的問題。
>
> ⚠️ **權限安全暫時方案**：bridge 仍用 `--dangerously-skip-permissions` 自動核准工具權限
> （不放大上述 sandbox 邊界，但會跳過逐次授權提示，對不特定使用者開放有 prompt-injection
> 風險）。徹底正解是把工具做成 MCP server（見 ARCHITECTURE.md「權限與安全」），尚未實作。

### 開發階段：看 Agent 用了哪些工具 + 保存對話

bridge 以 `--output-format stream-json` 呼叫 `agy`，解析 NDJSON 事件流，取得
Agent 這一輪**實際呼叫的工具序列**（`run_command`/`find_by_name`/`view_file`…）與最終回覆。

- **回覆附工具清單**：`/ask` 回覆末尾會加一行 `🔧 本次用了：run_command(python tools/get_stock_price.py 2330)、…`。
  預設開啟（開發友善）；上線後設環境變數 `SHOW_AGENT_TOOLS=0` 即可關閉，不需改碼。
- **保存所有對話**：每次 `/ask` 交換（時間、user/chat id、問題、回覆、工具清單、
  usage、conversation_id）會 append 一行 JSON 到 `data/logs/agent_conversations.jsonl`
  （已被 `.gitignore` 排除；寫入為 best-effort，失敗只記 log 不影響回覆）。

### 定時 AI Log 稽核（`bot/log_audit.py`）

每隔 `log_audit_interval_min` 分鐘（預設 1440 = 一天一次）跑一次排程 job，把**上次稽核後新增**
的 log 交給 Agent（AI）判讀，發現問題就通知 `TELEGRAM_ADMIN_CHAT_ID`：

- **執行問題**：`data/logs/bot.log` 的錯誤、例外堆疊、重複失敗、連線異常。
- **對話異常 / 惡意使用**：`agent_conversations.jsonl` 中的 prompt injection 嘗試、誘導 Agent
  執行破壞性或與台股無關的系統指令、濫用/探測系統等。

AI 只需回傳 `OK` 或 `ISSUES` + 條列問題；**只有判為 `ISSUES` 才發告警，`OK` 不通知**。稽核游標存在
`data/logs/audit_state.json`（bot.log offset + 對話行數），確保每次只看新內容、不重複稽核；
AI 呼叫失敗時不推進游標，下一輪會重試同一區間。讀 `bot.log` 時會**過濾掉稽核模組自己的
`bot.log_audit` 記帳行**，避免稽核把自己發的告警當成新問題而形成自我循環。

> 🔒 **prompt-injection 防護**：稽核 prompt 明確要求 AI 把 BEGIN/END 標記間的所有 log 內容
> 當「待稽核資料」而非指令，即使 log 中出現「忽略先前指示」等字樣也不遵從。

## 工具（獨立 CLI）

每個工具都能單獨在命令列執行，回傳 JSON。所有工具皆為純粹確定性程式，**本身不呼叫 AI**
（由 Agent 協調 `chat_bot → AI → tool → AI → tool`）：

```bash
python tools/get_stock_price.py 2330                       # 即時股價（best-effort 附 UAnalyze 基本面）
python tools/uanalyze.py --fundamentals 2330               # 即時基本面摘要（收盤價/當日漲跌幅/本益比/最新財報/月營收/掛牌類別，供 /p 疊加）
python tools/draw_kchart.py 2330 --period 60               # K 線圖 → 圖片路徑
python tools/draw_intraday_chart.py 2330                   # 盤中分時走勢折線圖 → 圖片路徑
python tools/fetch_news.py --all                           # 全部 15 來源最新新聞
python tools/fetch_news.py 2330 --limit 5                  # 指定股票新聞（本地過濾）
python tools/uanalyze.py 2330                              # UAnalyze AI 估值分析
python tools/uanalyze.py --multi 2330 --prompts 近況發展,利多因素,利空因素   # 一次並行跑多個面向（做完整報告用，比逐一快）
python tools/uanalyze.py --reports --limit 50              # UAnalyze 最新研究報告列表（監控用）
python tools/uanalyze.py --consensus 2330                  # 法人共識（單季 EPS 實際 vs 預估 + 月營收共識）摘要
python tools/uanalyze.py --pershare 2330                   # 近年每股財務指標摘要（FCF/EPS/EBITDA/ROE/ROIC…）
python tools/uanalyze.py --supply 2330                     # 供應鏈（同業/供應鏈對照標的代號清單）
python tools/uanalyze.py --order 2330                      # 訂單能見度（訂單能見度 + 合約負債，資料稀疏可能無資料）
python tools/uanalyze.py --dcf 2330                        # DCF 估值（時間加權動態 DCF，純計算回內在價值/前瞻價值/信心度，非 AI）
python tools/uanalyze.py --transcript 2330                 # 法說會逐字稿清單（列歷次日期 + id）
python tools/uanalyze.py --transcript 2330 202607162330    # 某場逐字稿摘要（title/date/字數 + 全文前 500 字，非 16K 全文）
python tools/summarize_document.py https://example.com/x   # URL/PDF 摘要
python tools/lookup_stock_name.py 2330                     # 查代號→公司名（對照表）
python tools/lookup_stock_name.py --set 9999 某公司        # 手動寫回對照表（後援）
python tools/lookup_stock_name.py --refresh                # 從 UAnalyze StockPool 全表刷新對照表
```

### 原始資料工具（raw-data，CLI + import 雙入口）

以下工具把各資料源「能拿的資料」各做成獨立 function，供 Agent 按需呼叫、也可被
`tools/valuation.py` import。皆回 JSON、不呼叫 AI。

```bash
# 鉅亨網 CNYES（免金鑰）
python tools/cnyes.py --eps 2330            # FactSet 各年度預估 EPS
python tools/cnyes.py --target 2330         # 分析師目標價共識
python tools/cnyes.py --quote 2330          # 即時報價（數字代碼欄位已解碼）
python tools/cnyes.py --candles 2330 --days 365   # 歷史日K線

# FinMind（需 FINMIND_TOKENS）
python tools/finmind.py --per 2330          # 本益比/淨值比/殖利率歷史序列
python tools/finmind.py --price 2330        # 日收盤價量
python tools/finmind.py --revenue 2330      # 月營收
python tools/finmind.py --income 2330       # 綜合損益表
python tools/finmind.py --balance 2330      # 資產負債表
python tools/finmind.py --cashflow 2330     # 現金流量表
python tools/finmind.py --dividend 2330     # 股利政策
python tools/finmind.py --institution 2330  # 三大法人買賣超
python tools/finmind.py --margin 2330       # 融資融券
python tools/finmind.py --shareholding 2330 # 外資持股比率
python tools/finmind.py --info 2330         # 基本資料（名稱/產業/上市櫃）
python tools/finmind.py --news 2330         # 相關新聞

# 富果 Fugle（需 FUGLE_API_KEY）
python tools/fugle.py --quote 2330          # 即時報價（含五檔）
python tools/fugle.py --ticker 2330         # 交易屬性（漲跌停/產業/可否當沖）
python tools/fugle.py --candles 2330 --days 1277   # 歷史日K（>1年自動分段合併）
python tools/fugle.py --intraday-candles 2330      # 當日分鐘K
python tools/fugle.py --trades 2330         # 當日成交明細
python tools/fugle.py --volumes 2330        # 當日分價量
python tools/fugle.py --stats 2330          # 52週高低/成交統計

# Yahoo Finance（yfinance，免金鑰）
python tools/yfinance_data.py --info 2330       # 精選基本面欄位
python tools/yfinance_data.py --target 2330     # 分析師目標價 + 評等
python tools/yfinance_data.py --history 2330 --period 1y   # 歷史價
python tools/yfinance_data.py --financials 2330 # 年度損益表
```

### 估值工具（`tools/valuation.py`）

不直接打 API，而是 import 上述 raw-data function 拿資料、套用估值公式（數學核心搬自舊版
`math_utils.py`，純 numpy）。回 JSON、不呼叫 AI。

```bash
python tools/valuation.py --lohas 2330 --years 3.5   # 樂活五線譜（股價線性回歸 ±3SD 七線 + 回歸機率）← Fugle 歷史K
python tools/valuation.py --pe 2330                  # PE 河流圖（歷史本益比四分位 + ±3SD 帶 + 現值百分位）← FinMind
python tools/valuation.py --pb 2330                  # PB 河流圖（歷史股價淨值比，同上）← FinMind
python tools/valuation.py --eps-momentum 2330        # EPS 動能（FactSet 跨年度預估上/下修趨勢）← CNYES
python tools/valuation.py --target 2330              # 目標價彙整（CNYES 分析師共識 + Yahoo 目標均價）← CNYES + yfinance
python tools/valuation.py --all 2330                 # 全部彙整
```

### 個股新聞如何過濾

台股新聞標題寫公司中文名（「台積電」）而非代號（2330）。`fetch_news.py <代號>` 會：
1. 查 `lookup_stock_name.py` 的代號↔名稱對照表，補上公司名當關鍵字；
2. 從已抓取的 15 來源新聞池，本地過濾出標題/摘要含關鍵字的文章。

對照表（`data/stock_names.json`）主資料來自 **UAnalyze 官方 gidp StockPool 全台股名對照
（~12,361 檔）**，由 `--refresh` 灌入、之後每週自動刷新（過期才重抓）。首次部署請先跑一次
`python tools/lookup_stock_name.py --refresh`。`--set` 手動寫回退化為**後援**：只在
StockPool 未涵蓋某檔時補一筆（刷新不會碾掉手動項），內建 20 檔 seed 為最後後援。工具本身不呼叫 AI。

## 新聞來源（15 個）

CNYES、MoneyDJ、Yahoo股市、UDN財經、UAnalyze、UAnalyze專欄、Fugle、Vocus（特定作者）、FinGuider、Fintastic、Forecastock、NewsDigestAI、SinoTrade、Pocket學堂、Buffett Letters + Howard Marks Memos。

部分來源有 Cloudflare / SSL 保護，已分別處理：
- SSL 憑證問題（MoneyDJ / Pocket / FinGuider / SinoTrade）→ `verify=False`
- Cloudflare（Fintastic）→ WordPress REST API + 完整瀏覽器 UA

## 資料儲存

執行期資料存為 JSON（`data/`，已被 `.gitignore` 排除）：

- `subscriptions.json` — 訂閱清單
- `news_cache.json` — 新聞內容快取（TTL 10 分鐘，避免每次重抓 15 來源）
- `pushed_news.json` — 已推新聞 URL（保留 7 天）
- `pushed_uanalyze.json` — 已推 UAnalyze 報告 id（保留 14 天，監控去重用）
- `stock_names.json` — 代號↔公司名對照表（UAnalyze StockPool 全表 ~12,361 檔，每週刷新，`--set` 手動後援）
- `stock_names_meta.json` — 對照表刷新時間戳（判斷是否過期需重抓）
- `logs/agent_conversations.jsonl` — 每次 `/ask` 對話記錄（問題/回覆/工具清單/usage，append-only）
- `logs/audit_state.json` — Log 稽核游標（已稽核到的 bot.log offset 與對話行數，避免重複稽核）
- `logs/bot.log` — WARNING 以上日誌（rotation，5MB × 5）

## 測試

```bash
source .venv/bin/activate
python -m pytest tests/ -q
```

目前 **429 個測試全數通過**，皆為單元測試（外部相依以 mock 隔離）。

### 端到端驗證現況

| 項目 | 狀態 |
|------|------|
| 15 個新聞來源（真網路抓取） | ✅ 已手動實測（前 14 來源可用；UAnalyze 專欄走 JWT 實打驗證） |
| `fetch_news <代號>` 個股過濾 | ✅ 已手動實測 |
| 代號對照表 命中/miss/寫回/再命中 | ✅ CLI 實測 |
| `/ask` → `agy` → 跑工具 → 回真實數據 | ✅ 透過真實 bridge 實測 |
| UAnalyze 真登入 + 分析 | ✅ 真憑證實測（`/ua`、`analyze()`） |
| `python main.py` 啟動 → 連上 Telegram → 排程啟動 → 乾淨關閉 | ✅ 實際啟動驗證 |
| **手機端互動**（真人發指令、`/ask`、排程實際推播到訂閱者） | ❌ 尚未測試（需真人操作） |
| Docker build | ❌ 尚未實跑 |
| 自動化 e2e 測試 | ❌ 無（目前僅單元測試） |

## 專案結構

```
main.py                 # 進入點
bot/
├── handlers.py         # Telegram 訊息處理 + /ask 路由與回覆格式
├── scheduler.py        # APScheduler 新聞 / UAnalyze 推播 job
├── subscriptions.py    # /sub_* /unsub_* /news 指令
├── reply_format.py     # 解析 Agent 回覆的 FORMAT: text/html/markdown 標記
├── reply_docs.py       # 把 html/markdown 回覆包成 .html/.md 附件內容
├── tables.py           # 等寬文字表格 helper
├── logging_conf.py     # 日誌設定（stdout + file rotation）
├── error_notify.py     # 排程失敗 retry + 管理者通知
└── log_audit.py        # 定時 AI log 稽核
agent/
├── bridge.py           # AgentBridge ABC + AntigravityCLIBridge
├── prompts.py          # Agent prompt templates
└── conversation_log.py # /ask 對話記錄
tools/                  # 12 個工具 script（CLI + import 雙入口）
data/                   # 執行期 JSON + 日誌
tests/                  # 429 個測試
```
