# Stock Bot 架構 Spec

> AI Agent + Telegram 混合架構 — 台股投資輔助 Bot

## 1. 系統概覽

```
┌─────────────────────────────────────────────────────────┐
│                   Single Python Process                   │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Telegram Bot  │  │  APScheduler │  │   Logging    │  │
│  │  (薄殼)      │  │  (排程 Job)  │  │              │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘  │
│         │                  │                             │
│         ▼                  ▼                             │
│  ┌─────────────────────────────────┐                    │
│  │         tools/ (共用邏輯)        │                    │
│  │  Python scripts — 雙入口         │                    │
│  │  • import (Bot 直接用)           │                    │
│  │  • CLI (Agent 透過 shell 執行)   │                    │
│  └─────────────────────────────────┘                    │
│         │                                                │
│         ▼                                                │
│  ┌─────────────────────────────────┐                    │
│  │      AgentBridge (ABC)           │                    │
│  │  └─ AntigravityCLIBridge         │                    │
│  │     subprocess: agy -p "..."     │                    │
│  └─────────────────────────────────┘                    │
│                                                          │
│  ┌──────────────┐                                       │
│  │  data/ (JSON) │  訂閱、已推 ID                       │
│  └──────────────┘                                       │
└─────────────────────────────────────────────────────────┘
```

## 2. 三層架構

| 層 | 職責 | 不做 |
|----|------|------|
| **Bot 薄殼** | 收發 Telegram 訊息、處理 `/ask` 指令、排程管理、訂閱指令 | 不做 AI 推理 |
| **Agent 路由** | 理解用戶意圖、決定呼叫哪個 tool、組合回覆 | 不做 Telegram I/O |
| **Tools** | 純業務邏輯（抓資料、算分析、畫圖） | 不知道 Telegram 或 Agent 的存在 |

## 3. 觸發方式

### 用戶互動 → Agent

- 用戶在群組或私訊中送出 **`/ask <問題>`**（群組、私訊皆可，不需 @mention）
- Bot 以 `CommandHandler("ask", ...)` 接收，提取 `/ask` 後的文字（空則回用法提示、不呼叫 Agent）
- 透過 `AgentBridge.send(prompt)` 交給 Antigravity CLI
- Agent 自行決定要跑哪些 tool、組合回覆
- Bot 把 Agent 回覆發回 Telegram

### Bot 直接處理（不經 Agent）

| 指令 | 功能 |
|------|------|
| `/start` `/help` | 歡迎訊息 / 指令與功能說明 |
| `/sub_news` | 訂閱新聞推播 |
| `/unsub_news` | 取消新聞推播 |
| `/sub_ua_reports` | 訂閱 UAnalyze 新研究報告推播 |
| `/unsub_ua_reports` | 取消 UAnalyze 新研究報告推播 |
| `/p <代號>` | 即時股價（直接 import 工具，不經 AI），best-effort 附 UAnalyze 基本面 |
| `/k <代號> [天數]` | K 線圖（回傳圖片） |

> 快捷指令 `/p` `/k` 直接呼叫對應工具、不經 Agent（省 token、秒回）；估值/財務/新聞/逐字稿等
> 進階查詢改用 `/ask` 交給 Agent。**v2 起 `/ua` `/data` `/news` 互動選單已移除**（底層工具仍在，
> Agent 照常呼叫）；推播訂閱不受影響。

## 4. Agent 接入方式

### 現行方案：Antigravity CLI Headless

```python
import asyncio, json

class AntigravityCLIBridge(AgentBridge):
    async def send(self, prompt: str) -> str:
        # 實際實作：prompt 走 stdin（--input-format stream-json，一行 NDJSON），
        # 輸出也是 stream-json（NDJSON 事件流），逐行解析取工具序列與最終回覆。
        proc = await asyncio.create_subprocess_exec(
            "agy", "-p", "",                      # prompt 走 stdin，故 -p 帶空字串
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--print-timeout", f"{timeout}s",     # 與外層 wait 對齊，避免過早逾時
            "--sandbox", "--add-dir", REPO_ROOT,
            "--dangerously-skip-permissions",
            cwd=REPO_ROOT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate(_encode_prompt(prompt))
        return _parse_ndjson_final_text(stdout)   # 解析事件流，取最終回覆

    async def is_available(self) -> bool:
        proc = await asyncio.create_subprocess_exec("agy", "--version", ...)
        return proc.returncode == 0
```

### 特性

- **無狀態**：每次 `/ask` 都是獨立一問一答，不保留多輪 context
- **非阻塞**：`asyncio.create_subprocess_exec` 不卡 event loop
- **錯誤處理**：超時或 exit code 非 0 → 回覆用戶「Agent 暫時無法回應，請稍後再試」
- **未來可切換**：有 API key 後可加 `AntigravitySDKBridge` 實作，呼叫端不改
- **System prompt**：`agent/prompts.py` 的 `build_mention_prompt()` 在每次 `/ask` 前
  組合角色（台股助理）+ 工具清單 + cwd 說明，讓 Agent 知道有哪些工具、怎麼呼叫。
- **關在專案 workspace**：bridge spawn `agy` 時指定 `cwd=REPO_ROOT`，並加
  `--sandbox --add-dir REPO_ROOT`，工具用相對路徑 `tools/xxx.py`；Agent 無法存取專案目錄外的檔案。

### 搜尋範圍限制（已實作）與權限安全（待辦）

**搜尋範圍限制（已實作）**：bridge spawn `agy` 時加 `--sandbox --add-dir REPO_ROOT`，
把 Agent 關在專案 workspace 內。實測結果：Agent 可正常執行 `python tools/xxx.py`
（回 `SUCCESS`），但對專案目錄以外的路徑做 `find` / 讀檔會被擋（回「被限制」）。
這解決了先前 Agent 偶爾會掃整台電腦的問題。

**權限安全（暫時方案）**：bridge 仍用 `--dangerously-skip-permissions` 自動核准工具權限。
這不會放大上述 sandbox 邊界（專案外仍被擋），但會跳過逐次授權提示——若 bot 對不特定
使用者開放，仍存在 prompt-injection 風險。先前試過用 `settings.json` 的 `permissions.allow`
白名單「只放行工具」但難以在「只放行工具」與「Agent 正常運作」間取得平衡。

**徹底正解（待辦）**：把工具註冊為 **MCP server**（`agy mcp add`），Agent 只能呼叫這些
MCP 工具、完全不碰任意 shell，天生防 prompt injection。這也是 ticket 03 的原始設計方向。

### 為什麼不用 SDK

Google AI Pro 方案不提供 `GEMINI_API_KEY`，SDK 需要此 key 才能執行。CLI headless 使用登入 session 認證。

## 5. Tool 設計

### 原則

- 每個 tool 是獨立 Python script
- 檔頭 docstring 描述用途、用法、回傳格式
- Agent 讀檔頭就知道怎麼用，自行決定執行
- 統一 stdout JSON output
- Bot 排程可直接 `from tools.xxx import func`

### Tool 清單

| Script | 功能 | 範例用法 |
|--------|------|----------|
| `tools/analysis/news.py` | 15 來源新聞聚合 + 個股過濾（import raw/news_sources） | `python tools/analysis/news.py 2330 --limit 5` |
| `tools/raw/uanalyze.py` | UAnalyze 28 端點 raw fetcher（一端點一 function，只抓不組合） | `python tools/raw/uanalyze.py historical_per 2330` |
| `tools/analysis/get_stock_price.py` | 即時股價（best-effort 附基本面，走 analysis/fundamentals） | `python tools/analysis/get_stock_price.py 2330` |
| `tools/analysis/draw_kchart.py` | K 線圖（mplfinance 繪製，回傳圖片路徑） | `python tools/analysis/draw_kchart.py 2330 --period 60` |
| `tools/analysis/summarize_document.py` | URL/PDF 文件擷取 + AI 摘要（唯一呼叫 AI 的 analysis） | `python tools/analysis/summarize_document.py https://...` |
| `tools/lookup_stock_name.py` | 代號↔公司名對照表（純資料讀/寫；主資料為 UAnalyze StockPool 全表） | `python tools/lookup_stock_name.py 2330` |
| `tools/analysis/draw_intraday_chart.py` | 盤中分時走勢折線圖（回傳圖片路徑） | `python tools/analysis/draw_intraday_chart.py 2330` |
| `tools/raw/news_sources.py` | 15 新聞來源各一 fetcher + 全部並行抓取 + 單篇全文（只抓不過濾） | `python tools/raw/news_sources.py` |
| `tools/raw/broker_reports.py` | 券商研究報告（單一 Drive 來源）：查索引/抓單篇全文/重建索引 | `python tools/raw/broker_reports.py --stock 2330` |
| `tools/raw/cnyes.py` | 鉅亨網 raw：FactSet 預估EPS / 分析師目標價 / 即時報價 | `python tools/raw/cnyes.py --target 2330` |
| `tools/raw/finmind.py` | FinMind raw：PER/PBR、價量、月營收、三大財報、股利、法人、融資券、外資持股、基本資料、新聞 | `python tools/raw/finmind.py --per 2330` |
| `tools/raw/fugle.py` | 富果 raw：報價/交易屬性/盤中K・成交・分價量/歷史日K/52週統計 | `python tools/raw/fugle.py --quote 2330` |
| `tools/raw/yfinance_data.py` | Yahoo Finance raw：基本面 info / 分析師目標價+評等 / 歷史價 / 年度財報 | `python tools/raw/yfinance_data.py --target 2330` |
| `tools/analysis/valuation.py` | 估值計算（import raw）：樂活五線譜 / PE・PB 河流圖 / EPS 動能 / 目標價 / DCF / PE-PB Band（--dcf --csv 可多檔） | `python tools/analysis/valuation.py --dcf 2330` |
| `tools/analysis/fundamentals.py` | 即時基本面（/p 用，best-effort，import raw/uanalyze） | `python tools/analysis/fundamentals.py 2330` |
| `tools/analysis/forecast.py` | 法人前瞻預估整理（SmartEstimate / 未來五季路徑+評等） | `python tools/analysis/forecast.py --smart-estimate 2330` |
| `tools/analysis/reports.py` | UAnalyze 研究報告清單（推播/Agent 用，import raw/uanalyze） | `python tools/analysis/reports.py 2330` |

> **工具不呼叫 AI**：所有工具皆為純粹確定性程式。對照表主資料由 `lookup_stock_name.py`
> `--refresh` 從 UAnalyze StockPool 全表拉取灌入（純資料拉取，非 AI）；StockPool 仍未涵蓋
> 某檔時，才回退給 Agent 判斷公司名再 `--set` 寫回（後援），維持
> `chat_bot → AI → tool → AI → tool` 的協調管線，避免工具反向依賴 Agent。

### 個股新聞過濾

台股標題寫公司中文名而非代號。`analysis/news.py <代號>` 從 15 來源新聞池本地過濾出含
關鍵字（代號 + 對照表補上的公司名）的文章。對照表 `data/stock_names.json` 主資料為
UAnalyze StockPool 全台股名對照（~12,361 檔，每週刷新），未命中時 Agent 才 `--set` 補後援。

### Script 結構範例

```python
"""news — 15 來源新聞聚合 + 個股過濾（analysis 層，import raw/news_sources）
用法: python tools/analysis/news.py [SYMBOL|公司名] [--limit N] | --fulltext <URL>
回傳: JSON {"articles": [{title, source, date, url, summary}]}
"""

import asyncio, json, sys

async def fetch(symbol: str = None, limit: int = 10) -> dict:
    """核心邏輯 — Bot 排程也直接 import 這個（symbol 省略＝全來源最新）"""
    ...

async def latest() -> dict:
    """抓全部來源最新新聞 — 排程推播用"""
    ...

if __name__ == "__main__":
    # CLI 入口 — Agent 透過 shell 執行
    args = sys.argv[1:]
    if args and args[0] == "--fulltext" and len(args) > 1:
        result = asyncio.run(fetch_fulltext(args[1]))   # 單篇全文（轉呼 raw）
    else:
        symbol = next((a for a in args if not a.startswith("--")), None)
        limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10
        result = asyncio.run(fetch(symbol, limit))      # symbol=None → 全來源最新
    print(json.dumps(result, ensure_ascii=False))
```

### Output 規範

```json
// 成功
{"articles": [...]}

// 圖片
{"image_path": "/tmp/kchart_2330.png"}

// 錯誤（搭配非零 exit code）
{"error": "找不到股票代號 9999"}
```

## 6. 排程與推播

### 排程器：APScheduler（同 process）

| Job | 頻率（config 預設） | 流程 |
|-----|------|------|
| 新聞推播 `news_push` | 每小時 | `analysis/news.latest()` → URL + 標題模糊去重 → **直接送「標題＋URL 清單」**（無 AI 摘要、省 token）→ 推 Telegram |
| UAnalyze 報告監控 `uanalyze_push` | 每 30 分鐘 | `reports.list_latest_reports()` → 依 report id 去重 → 直接推 Telegram（無 AI、無關鍵字過濾，每則新報告一律正常通知；首次執行只建立去重狀態不洗版） |
| AI Log 稽核 `log_audit` | 每天（1440 分） | 讀 bot.log + 對話記錄增量 → Agent 判讀 → 只有 `ISSUES` 才通知管理者（游標存 audit_state.json） |
| 股名對照刷新 `stock_pool_refresh` | 每週 + 開機一次 | `lookup_stock_name.refresh_pool()`（表未過期則 no-op） |
| 券商報告索引同步 `broker_reports_sync` | 每小時 + 開機一次（`broker_sync_interval_min`） | `broker_reports.drive_sync()`（缺憑證則略過，不丟例外） |

### 推播流程

```
新聞：
  排程觸發 → news.latest() → 拿到新文章
  → 過濾已推 URL + 標題模糊去重 → 組「• [來源] 標題 └ URL」清單（不經 Agent）
  → 推給訂閱者（任一送達才標記 pushed，全逾時則下輪重送）
```

### 失敗處理

- 自動 retry 1-2 次
- 連續失敗 → 推 Telegram 通知管理者（admin chat_id）
- 所有失敗寫 log

## 7. 資料層

### 儲存方式：JSON 檔案

```
data/
├── subscriptions.json      # 訂閱資料
├── pushed_news.json        # 已推新聞 URL（保留 7 天）
└── logs/                   # log 檔案
```

### subscriptions.json 結構

```json
{
  "news": [{"chat_id": 123456, "thread_id": null, "subscribed_at": "2026-08-22T03:00:00"}],
  "uanalyze": [{"chat_id": -1001234, "thread_id": 42, "subscribed_at": "2026-08-22T03:00:00"}]
}
```

- 訂閱單位是複合鍵 `(chat_id, thread_id)`：`thread_id` 是群組論壇主題的 `message_thread_id`，私訊與群組 General 頻道為 `null`。同一群組不同 topic 可各自獨立訂閱。
- 舊版資料（只有 `chat_id`、無 `thread_id` 欄位）自動視為 `thread_id = null`，無需遷移。

### pushed_news.json 結構

```json
[
  {"url": "https://...", "pushed_at": "2026-08-22T03:00:00"},
  ...
]
```

### TTL 清理

- 新聞已推 URL：保留 **7 天**
- 排程 job 執行時順便清理過期資料

### Agent 不存取資料層

Agent 只透過 tool script 拿即時資料，不碰 `data/` 目錄。

## 8. 新聞來源（15 個）

| # | 來源 | 格式（實作） |
|---|------|------|
| 1 | CNYES 鉅亨網 | JSON API |
| 2 | MoneyDJ | RSS（`verify=False`，SSL 憑證問題） |
| 3 | Yahoo 股市 | RSS |
| 4 | UDN 聯合新聞網（財經版） | RSS（4 個 feed 並行合併） |
| 5 | UAnalyze | HTML（BeautifulSoup 解析） |
| 6 | Fugle | HTML（blog 分類頁爬 /post/ 連結） |
| 7 | Vocus 方格子（特定作者） | Next.js SSR（`__NEXT_DATA__`） |
| 8 | FinGuider | JSON API（`verify=False` fallback） |
| 9 | Fintastic | WordPress REST API（`/wp-json/wp/v2/posts` + 完整瀏覽器 UA） |
| 10 | Forecastock | HTML（直接爬，繞過失效的 morss proxy） |
| 11 | NewsDigest AI | RSS |
| 12 | SinoTrade 永豐 | GraphQL POST（`verify=False`） |
| 13 | Pocket 學堂 | JSON API（`verify=False`） |
| 14 | UAnalyze 專欄 | JSON API（`data/fetch/column/search`，JWT Bearer；付費內容無公開 permalink） |
| 15 | Buffett Letters + Howard Marks Memos | 靜態參考連結 |

**已砍：** Google News TW（雜訊多）、MacroMicro 財經M平方（已移除）

> **反爬蟲對策**：morss.it 公開 proxy 已失效，改為直接抓取。SSL 憑證問題的來源用 `verify=False`；Fintastic 用 WordPress API + 瀏覽器 UA。實測前 14 個來源全部可用；第 15 來源 UAnalyze 專欄走 JWT Bearer 實打驗證。

## 9. 部署

### 雙支援

```bash
# 開發
python main.py

# 部署
docker compose up -d
```

### 專案結構

```
stock-bot/
├── main.py                 # Entry point
├── bot/
│   ├── handlers.py         # Telegram message handlers + /ask 回覆格式路由
│   ├── scheduler.py        # APScheduler jobs
│   ├── subscriptions.py    # /sub_* /unsub_* 管理
│   ├── reply_format.py     # 解析 Agent 回覆第一行 FORMAT: text/html/markdown 標記
│   ├── reply_docs.py       # 把 html/markdown 回覆包成 .html/.md 檔案內容（附件）
│   ├── tables.py           # 等寬文字表格 helper（/data 等呈現用）
│   ├── logging_conf.py     # 日誌設定
│   ├── error_notify.py     # 排程失敗 retry + 管理者通知
│   └── log_audit.py        # 定時 AI log 稽核
├── agent/
│   ├── bridge.py           # AgentBridge ABC + AntigravityCLIBridge
│   ├── prompts.py          # Agent prompt templates
│   ├── quota_ledger.py     # 額度帳本 + token→額度% 校準
│   └── conversation_log.py # /ask 對話記錄（append-only jsonl）
├── tools/                  # 工具 script（CLI + import 雙入口）；raw 取數層 / analysis 功能層
│   ├── lookup_stock_name.py  # 代號↔公司名對照表（純本地，不歸兩層）
│   ├── raw/                # 純取數層（一端點/一資料源一 function，只抓不組合）
│   │   ├── uanalyze.py     #   UAnalyze 28 端點 raw fetcher
│   │   ├── cnyes.py
│   │   ├── finmind.py
│   │   ├── fugle.py
│   │   ├── yfinance_data.py
│   │   ├── news_sources.py #   15 新聞來源各一 fetcher + 單篇全文
│   │   └── broker_reports.py  # 券商報告（單一 Drive 來源）
│   └── analysis/           # 功能層（import raw 做計算/組合/繪圖/判讀）
│       ├── get_stock_price.py  # 即時股價（/p 用）
│       ├── draw_kchart.py
│       ├── draw_intraday_chart.py
│       ├── _chart_font.py  #   跨平台中文字型 fallback（繪圖共用 helper）
│       ├── news.py         #   新聞聚合 + 個股過濾
│       ├── summarize_document.py  # URL/PDF + AI 摘要
│       ├── valuation.py    #   估值 + DCF + PE-PB Band（含 DCF 批次 CSV）
│       ├── fundamentals.py #   即時基本面（/p 用）
│       ├── forecast.py     #   法人前瞻預估
│       └── reports.py      #   研究報告清單（推播用）
├── data/
│   ├── subscriptions.json
│   ├── pushed_news.json
│   └── logs/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

### 環境變數（`.env` — secrets only）

```env
# 必填
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_ADMIN_CHAT_ID=123456

# 資料來源
FINMIND_TOKENS=["token1","token2"]
FUGLE_API_KEY=xxx
UANALYZE_EMAIL=xxx
UANALYZE_PASSWORD=xxx
```

### 應用設定（`config.json` 或 code default）

```json
{
  "vocus_users": ["@ieobserve", "@miula", "65ab564cfd897800018a88cc"],
  "uanalyze_keywords": ["AI", "半導體", "ETF"],
  "news_schedule_interval_min": 60,
  "uanalyze_schedule_interval_min": 30,
  "log_audit_interval_min": 1440,
  "broker_sync_interval_min": 60
}
```

> `broker_sync_interval_min` 為可選鍵（未設時程式預設 60）。`vocus_users` 供 Vocus 新聞來源指定作者、`uanalyze_keywords` 為關鍵字設定。

## 10. 監控 / Logging

| 層級 | 輸出 |
|------|------|
| DEBUG / INFO | stdout（`docker logs` 看） |
| WARNING / ERROR | stdout + `data/logs/bot.log`（rotation） |
| CRITICAL（連續失敗） | 推 Telegram 通知管理者 |

## 11. 未來升級路徑

| 條件 | 動作 |
|------|------|
| 取得 `GEMINI_API_KEY` | 加 `AntigravitySDKBridge`，呼叫端不改 |
| 換 AI 框架 | 新增 `XxxBridge` 實作 `AgentBridge` ABC |
| 需要多輪對話 | 在 Bridge 加 `conversation_id` 參數 |
| 需要 DB | 把 JSON 換成 SQLite，data layer 獨立模組 |

## 12. Out of Scope

- Web 儀表板
- 情緒分析
- 每日自動分析 + 低估偵測
- MEGA 下載
- Podcast 摘要
- /chat AI 對話（由 @agent 取代）
- 自選股管理
- 爆量偵測（已移除）
