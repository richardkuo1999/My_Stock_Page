# Stock Bot — 台股投資輔助 Telegram Bot

AI Agent + Telegram 混合架構的台股投資輔助 Bot。Bot 薄殼負責收發訊息與排程推播，`@mention` 交給 Antigravity Agent 決定呼叫哪些工具，工具是一組獨立的 Python script（可 CLI 執行、也可 import）。

完整架構設計見 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 需求

- Python 3.12+
- （選用）Docker + Docker Compose
- （選用）Antigravity CLI（`agy` 指令）— `@mention` 問 Agent 才需要

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
  "log_audit_interval_min": 360
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
| `/news` | 跳出選單選新聞來源（全部或指定 16 來源之一），再回覆該來源最新新聞 |
| `/p <代號>` | 即時股價（直接跑工具，秒回），並 best-effort 附上 UAnalyze 基本面（本益比/最新財報/月營收等），例 `/p 2330` |
| `/k <代號> [天數]` | K 線圖（回傳圖片），例 `/k 2330 60` |
| `/ua <代號>` | UAnalyze AI 分析：跳出選單選分析面向（近況/產業/資本支出…），另含「法說會逐字稿」入口（列歷次法說會→選一場→分頁閱讀完整逐字稿全文，翻頁走記憶體快取不重打 API），例 `/ua 2330` |
| `/data <代號>` | 跳出選單選資料類型（法人共識 / 財務指標 / 供應鏈 / 訂單能見度 / DCF 估值），回濃縮數據，例 `/data 2330` |
| `@bot 你的問題` | 交給 Agent 處理（需先設定 Antigravity CLI，見下） |

> 快捷指令（`/p` `/k` `/ua` `/news`）直接呼叫工具、不經 AI，回應快且省 token；
> 需要組合多個工具或自然語言提問時才用 `@mention`。排程推播只發給訂閱者且會去重。

## Agent（`@mention`）

`@bot` 問問題時，Bot 透過 `AntigravityCLIBridge` 呼叫 `agy -p "..." --output-format json`。
需先在本機安裝並登入 Antigravity CLI（`agy` 指令）。未安裝時 `@mention` 會回覆錯誤訊息，其餘功能不受影響。

每次 `@mention` 會由 `agent/prompts.py` 的 `build_mention_prompt()` 組合 system prompt
（角色=台股助理 + 6 個工具清單 + 執行流程）再送給 Agent，Agent 據此決定要跑哪些工具。

> ⚠️ **安全暫時方案**：目前 bridge 用 `--dangerously-skip-permissions` 讓 headless Agent
> 能執行工具，這會授予 Agent 無限制指令執行權限（對不特定使用者開放有 prompt-injection
> 風險）。正解是把工具做成 MCP server（見 ARCHITECTURE.md「權限與安全」），尚未實作。

### 開發階段：看 Agent 用了哪些工具 + 保存對話

bridge 以 `--output-format stream-json` 呼叫 `agy`，解析 NDJSON 事件流，取得
Agent 這一輪**實際呼叫的工具序列**（`run_command`/`find_by_name`/`view_file`…）與最終回覆。

- **回覆附工具清單**：`@mention` 回覆末尾會加一行 `🔧 本次用了：run_command(python tools/get_stock_price.py 2330)、…`。
  預設開啟（開發友善）；上線後設環境變數 `SHOW_AGENT_TOOLS=0` 即可關閉，不需改碼。
- **保存所有對話**：每次 `@mention` 交換（時間、user/chat id、問題、回覆、工具清單、
  usage、conversation_id）會 append 一行 JSON 到 `data/logs/agent_conversations.jsonl`
  （已被 `.gitignore` 排除；寫入為 best-effort，失敗只記 log 不影響回覆）。

### 定時 AI Log 稽核（`bot/log_audit.py`）

每隔 `log_audit_interval_min` 分鐘（預設 360 = 6 小時）跑一次排程 job，把**上次稽核後新增**
的 log 交給 Agent（AI）判讀，發現問題就通知 `TELEGRAM_ADMIN_CHAT_ID`：

- **執行問題**：`data/logs/bot.log` 的錯誤、例外堆疊、重複失敗、連線異常。
- **對話異常 / 惡意使用**：`agent_conversations.jsonl` 中的 prompt injection 嘗試、誘導 Agent
  執行破壞性或與台股無關的系統指令、濫用/探測系統等。

AI 只需回傳 `OK` 或 `ISSUES` + 條列問題；判為 `ISSUES` 才發告警。稽核游標存在
`data/logs/audit_state.json`（bot.log offset + 對話行數），確保每次只看新內容、不重複稽核；
AI 呼叫失敗時不推進游標，下一輪會重試同一區間。

> 🔒 **prompt-injection 防護**：稽核 prompt 明確要求 AI 把 BEGIN/END 標記間的所有 log 內容
> 當「待稽核資料」而非指令，即使 log 中出現「忽略先前指示」等字樣也不遵從。

## 工具（獨立 CLI）

每個工具都能單獨在命令列執行，回傳 JSON。所有工具皆為純粹確定性程式，**本身不呼叫 AI**
（由 Agent 協調 `chat_bot → AI → tool → AI → tool`）：

```bash
python tools/get_stock_price.py 2330                       # 即時股價（best-effort 附 UAnalyze 基本面）
python tools/uanalyze.py --fundamentals 2330               # 即時基本面摘要（收盤價/當日漲跌幅/本益比/最新財報/月營收/掛牌類別，供 /p 疊加）
python tools/draw_kchart.py 2330 --period 60               # K 線圖 → 圖片路徑
python tools/fetch_news.py --all                           # 全部 16 來源最新新聞
python tools/fetch_news.py 2330 --limit 5                  # 指定股票新聞（本地過濾）
python tools/uanalyze.py 2330                              # UAnalyze AI 估值分析
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

### 個股新聞如何過濾

台股新聞標題寫公司中文名（「台積電」）而非代號（2330）。`fetch_news.py <代號>` 會：
1. 查 `lookup_stock_name.py` 的代號↔名稱對照表，補上公司名當關鍵字；
2. 從已抓取的 16 來源新聞池，本地過濾出標題/摘要含關鍵字的文章。

對照表（`data/stock_names.json`）主資料來自 **UAnalyze 官方 gidp StockPool 全台股名對照
（~12,361 檔）**，由 `--refresh` 灌入、之後每週自動刷新（過期才重抓）。首次部署請先跑一次
`python tools/lookup_stock_name.py --refresh`。`--set` 手動寫回退化為**後援**：只在
StockPool 未涵蓋某檔時補一筆（刷新不會碾掉手動項），內建 20 檔 seed 為最後後援。工具本身不呼叫 AI。

## 新聞來源（16 個）

CNYES、MoneyDJ、Yahoo股市、UDN財經、UAnalyze、UAnalyze專欄、Fugle、Vocus（特定作者）、MacroMicro、FinGuider、Fintastic、Forecastock、NewsDigestAI、SinoTrade、Pocket學堂、Buffett Letters + Howard Marks Memos。

部分來源有 Cloudflare / SSL 保護，已分別處理：
- SSL 憑證問題（MoneyDJ / Pocket / FinGuider / SinoTrade）→ `verify=False`
- Cloudflare（MacroMicro）→ `curl_cffi` 偽裝 Chrome TLS 指紋
- Cloudflare（Fintastic）→ WordPress REST API + 完整瀏覽器 UA

## 資料儲存

執行期資料存為 JSON（`data/`，已被 `.gitignore` 排除）：

- `subscriptions.json` — 訂閱清單
- `news_cache.json` — 新聞內容快取（TTL 10 分鐘，避免每次重抓 16 來源）
- `pushed_news.json` — 已推新聞 URL（保留 7 天）
- `pushed_uanalyze.json` — 已推 UAnalyze 報告 id（保留 14 天，監控去重用）
- `stock_names.json` — 代號↔公司名對照表（UAnalyze StockPool 全表 ~12,361 檔，每週刷新，`--set` 手動後援）
- `stock_names_meta.json` — 對照表刷新時間戳（判斷是否過期需重抓）
- `logs/agent_conversations.jsonl` — 每次 `@mention` 對話記錄（問題/回覆/工具清單/usage，append-only）
- `logs/audit_state.json` — Log 稽核游標（已稽核到的 bot.log offset 與對話行數，避免重複稽核）
- `logs/bot.log` — WARNING 以上日誌（rotation，5MB × 5）

## 測試

```bash
source .venv/bin/activate
python -m pytest tests/ -q
```

目前 **262 個測試全數通過**，皆為單元測試（外部相依以 mock 隔離）。

### 端到端驗證現況

| 項目 | 狀態 |
|------|------|
| 16 個新聞來源（真網路抓取） | ✅ 已手動實測（前 15 來源 ~175 篇；UAnalyze 專欄走 JWT 實打驗證） |
| `fetch_news <代號>` 個股過濾 | ✅ 已手動實測 |
| 代號對照表 命中/miss/寫回/再命中 | ✅ CLI 實測 |
| `@mention` → `agy` → 跑工具 → 回真實數據 | ✅ 透過真實 bridge 實測 |
| UAnalyze 真登入 + 分析 | ✅ 真憑證實測（`/ua`、`analyze()`） |
| `python main.py` 啟動 → 連上 Telegram → 排程啟動 → 乾淨關閉 | ✅ 實際啟動驗證 |
| **手機端互動**（真人發指令、`@mention`、排程實際推播到訂閱者） | ❌ 尚未測試（需真人操作） |
| Docker build | ❌ 尚未實跑 |
| 自動化 e2e 測試 | ❌ 無（目前僅單元測試） |

## 專案結構

```
main.py                 # 進入點
bot/
├── handlers.py         # Telegram 訊息處理 + @mention 路由
├── scheduler.py        # APScheduler 新聞 / UAnalyze 推播 job
├── subscriptions.py    # /sub_* /unsub_* /news 指令
├── logging_conf.py     # 日誌設定（stdout + file rotation）
└── error_notify.py     # 排程失敗 retry + 管理者通知
agent/
├── bridge.py           # AgentBridge ABC + AntigravityCLIBridge
└── prompts.py          # Agent prompt templates
tools/                  # 6 個工具 script（CLI + import 雙入口）
data/                   # 執行期 JSON + 日誌
tests/                  # 262 個測試
```
