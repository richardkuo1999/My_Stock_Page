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
THREADS_ACCESS_TOKEN=     # Meta Threads 官方 API long-lived token
```

### 應用設定（`config.json` — 非機密）

```json
{
  "vocus_users": ["@ieobserve", "@miula", "65ab564cfd897800018a88cc"],
  "uanalyze_keywords": ["AI", "半導體", "ETF"],
  "news_schedule_interval_min": 60,
  "threads_schedule_interval_min": 15,
  "uanalyze_schedule_interval_min": 30,
  "threads_users": []
}
```

- `threads_users`：要追蹤的 Threads user ID 清單。留空時 `/threads` 與排程會 fallback 抓「自己帳號」的貼文。

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
| `/sub_threads` / `/unsub_threads` | 訂閱 / 取消 Threads 推播（每 15 分鐘） |
| `/sub_ua_reports` / `/unsub_ua_reports` | 訂閱 / 取消 UAnalyze 新研究報告推播（每 30 分鐘） |
| `/news` | 跳出選單選新聞來源（全部或指定 15 來源之一），再回覆該來源最新新聞 |
| `/threads` | 立即抓最新 Threads 貼文並回覆 |
| `/p <代號>` | 即時股價（直接跑工具，秒回），並 best-effort 附上 UAnalyze 基本面（本益比/最新財報/月營收等），例 `/p 2330` |
| `/k <代號> [天數]` | K 線圖（回傳圖片），例 `/k 2330 60` |
| `/ua <代號>` | UAnalyze AI 分析：跳出選單選分析面向（近況/產業/資本支出…），例 `/ua 2330` |
| `/data <代號>` | 跳出選單選資料類型（法人共識 / 財務指標 / 供應鏈 / 訂單能見度 / DCF 估值），回濃縮數據，例 `/data 2330` |
| `@bot 你的問題` | 交給 Agent 處理（需先設定 Antigravity CLI，見下） |

> 快捷指令（`/p` `/k` `/ua` `/news` `/threads`）直接呼叫工具、不經 AI，回應快且省 token；
> 需要組合多個工具或自然語言提問時才用 `@mention`。排程推播只發給訂閱者且會去重。

## Agent（`@mention`）

`@bot` 問問題時，Bot 透過 `AntigravityCLIBridge` 呼叫 `agy -p "..." --output-format json`。
需先在本機安裝並登入 Antigravity CLI（`agy` 指令）。未安裝時 `@mention` 會回覆錯誤訊息，其餘功能不受影響。

每次 `@mention` 會由 `agent/prompts.py` 的 `build_mention_prompt()` 組合 system prompt
（角色=台股助理 + 7 個工具清單 + 執行流程）再送給 Agent，Agent 據此決定要跑哪些工具。

> ⚠️ **安全暫時方案**：目前 bridge 用 `--dangerously-skip-permissions` 讓 headless Agent
> 能執行工具，這會授予 Agent 無限制指令執行權限（對不特定使用者開放有 prompt-injection
> 風險）。正解是把工具做成 MCP server（見 ARCHITECTURE.md「權限與安全」），尚未實作。

## 工具（獨立 CLI）

每個工具都能單獨在命令列執行，回傳 JSON。所有工具皆為純粹確定性程式，**本身不呼叫 AI**
（由 Agent 協調 `chat_bot → AI → tool → AI → tool`）：

```bash
python tools/get_stock_price.py 2330                       # 即時股價（best-effort 附 UAnalyze 基本面）
python tools/uanalyze.py --fundamentals 2330               # 即時基本面摘要（收盤價/當日漲跌幅/本益比/最新財報/月營收/掛牌類別，供 /p 疊加）
python tools/draw_kchart.py 2330 --period 60               # K 線圖 → 圖片路徑
python tools/fetch_news.py --all                           # 全部 15 來源最新新聞
python tools/fetch_news.py 2330 --limit 5                  # 指定股票新聞（本地過濾）
python tools/fetch_threads.py --check-new                  # 追蹤帳號 Threads 貼文
python tools/uanalyze.py 2330                              # UAnalyze AI 估值分析
python tools/uanalyze.py --reports --limit 50              # UAnalyze 最新研究報告列表（監控用）
python tools/uanalyze.py --consensus 2330                  # 法人共識（單季 EPS 實際 vs 預估 + 月營收共識）摘要
python tools/uanalyze.py --pershare 2330                   # 近年每股財務指標摘要（FCF/EPS/EBITDA/ROE/ROIC…）
python tools/uanalyze.py --supply 2330                     # 供應鏈（同業/供應鏈對照標的代號清單）
python tools/uanalyze.py --order 2330                      # 訂單能見度（訂單能見度 + 合約負債，資料稀疏可能無資料）
python tools/uanalyze.py --dcf 2330                        # DCF 估值（時間加權動態 DCF，純計算回內在價值/前瞻價值/信心度，非 AI）
python tools/summarize_document.py https://example.com/x   # URL/PDF 摘要
python tools/lookup_stock_name.py 2330                     # 查代號→公司名（對照表）
python tools/lookup_stock_name.py --set 9999 某公司        # 手動寫回對照表（後援）
python tools/lookup_stock_name.py --refresh                # 從 UAnalyze StockPool 全表刷新對照表
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

CNYES、MoneyDJ、Yahoo股市、UDN財經、UAnalyze、Fugle、Vocus（特定作者）、MacroMicro、FinGuider、Fintastic、Forecastock、NewsDigestAI、SinoTrade、Pocket學堂、Buffett Letters + Howard Marks Memos。

部分來源有 Cloudflare / SSL 保護，已分別處理：
- SSL 憑證問題（MoneyDJ / Pocket / FinGuider / SinoTrade）→ `verify=False`
- Cloudflare（MacroMicro）→ `curl_cffi` 偽裝 Chrome TLS 指紋
- Cloudflare（Fintastic）→ WordPress REST API + 完整瀏覽器 UA

## 資料儲存

執行期資料存為 JSON（`data/`，已被 `.gitignore` 排除）：

- `subscriptions.json` — 訂閱清單
- `news_cache.json` — 新聞內容快取（TTL 10 分鐘，避免每次重抓 15 來源）
- `pushed_news.json` — 已推新聞 URL（保留 7 天）
- `pushed_threads.json` — 已推 Threads ID（保留 3 天）
- `pushed_uanalyze.json` — 已推 UAnalyze 報告 id（保留 14 天，監控去重用）
- `stock_names.json` — 代號↔公司名對照表（UAnalyze StockPool 全表 ~12,361 檔，每週刷新，`--set` 手動後援）
- `stock_names_meta.json` — 對照表刷新時間戳（判斷是否過期需重抓）
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
| 15 個新聞來源（真網路抓取） | ✅ 已手動實測（~175 篇） |
| `fetch_news <代號>` 個股過濾 | ✅ 已手動實測 |
| 代號對照表 命中/miss/寫回/再命中 | ✅ CLI 實測 |
| `@mention` → `agy` → 跑工具 → 回真實數據 | ✅ 透過真實 bridge 實測 |
| UAnalyze 真登入 + 分析 | ✅ 真憑證實測（`/ua`、`analyze()`） |
| `python main.py` 啟動 → 連上 Telegram → 排程啟動 → 乾淨關閉 | ✅ 實際啟動驗證 |
| **手機端互動**（真人發指令、`@mention`、排程實際推播到訂閱者） | ❌ 尚未測試（需真人操作） |
| Threads 官方 API 真 token、Docker build | ❌ 尚未實跑 |
| 自動化 e2e 測試 | ❌ 無（目前僅單元測試） |

## 專案結構

```
main.py                 # 進入點
bot/
├── handlers.py         # Telegram 訊息處理 + @mention 路由
├── scheduler.py        # APScheduler 新聞 / Threads 推播 job
├── subscriptions.py    # /sub_* /unsub_* /news /threads 指令
├── logging_conf.py     # 日誌設定（stdout + file rotation）
└── error_notify.py     # 排程失敗 retry + 管理者通知
agent/
├── bridge.py           # AgentBridge ABC + AntigravityCLIBridge
└── prompts.py          # Agent prompt templates
tools/                  # 7 個工具 script（CLI + import 雙入口）
data/                   # 執行期 JSON + 日誌
tests/                  # 262 個測試
```
