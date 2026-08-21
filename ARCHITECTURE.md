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
| **Bot 薄殼** | 收發 Telegram 訊息、偵測 @mention、排程管理、訂閱指令 | 不做 AI 推理 |
| **Agent 路由** | 理解用戶意圖、決定呼叫哪個 tool、組合回覆 | 不做 Telegram I/O |
| **Tools** | 純業務邏輯（抓資料、算分析、畫圖） | 不知道 Telegram 或 Agent 的存在 |

## 3. 觸發方式

### 用戶互動 → Agent

- 用戶在群組或私訊中 **@bot_name** 或包含特定關鍵詞
- Bot 偵測 `MessageEntity.MENTION`，提取文字
- 透過 `AgentBridge.send(prompt)` 交給 Antigravity CLI
- Agent 自行決定要跑哪些 tool、組合回覆
- Bot 把 Agent 回覆發回 Telegram

### Bot 直接處理（不經 Agent）

| 指令 | 功能 |
|------|------|
| `/sub_news` | 訂閱新聞推播 |
| `/unsub_news` | 取消新聞推播 |
| `/sub_threads` | 訂閱 Threads 推播 |
| `/unsub_threads` | 取消 Threads 推播 |

## 4. Agent 接入方式

### 現行方案：Antigravity CLI Headless

```python
import asyncio, json

class AntigravityCLIBridge(AgentBridge):
    async def send(self, prompt: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "agy", "-p", prompt, "--output-format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        result = json.loads(stdout)
        return result["response"]

    async def is_available(self) -> bool:
        proc = await asyncio.create_subprocess_exec("agy", "--version", ...)
        return proc.returncode == 0
```

### 特性

- **無狀態**：每次 @agent 都是獨立一問一答，不保留多輪 context
- **非阻塞**：`asyncio.create_subprocess_exec` 不卡 event loop
- **錯誤處理**：超時或 exit code 非 0 → 回覆用戶「Agent 暫時無法回應，請稍後再試」
- **未來可切換**：有 API key 後可加 `AntigravitySDKBridge` 實作，呼叫端不改

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
| `tools/fetch_news.py` | 抓指定股票/全部最新新聞 | `python tools/fetch_news.py 2330 --limit 5` |
| `tools/uanalyze.py` | AI 估值分析 | `python tools/uanalyze.py 2330` |
| `tools/get_stock_price.py` | 即時股價 | `python tools/get_stock_price.py 2330` |
| `tools/draw_kchart.py` | K 線圖（回傳圖片路徑） | `python tools/draw_kchart.py 2330 --period 60` |
| `tools/fetch_threads.py` | 抓追蹤帳號 Threads 貼文 | `python tools/fetch_threads.py --check-new` |
| `tools/summarize_document.py` | URL/PDF 文件摘要 | `python tools/summarize_document.py https://...` |

### Script 結構範例

```python
"""fetch_news — 取得指定股票的最新新聞
用法: python tools/fetch_news.py [SYMBOL] [--limit N] [--all]
回傳: JSON {"articles": [{title, source, date, url, summary}]}
"""

import asyncio, json, sys

async def fetch(symbol: str = None, limit: int = 10) -> dict:
    """核心邏輯 — Bot 排程也直接 import 這個"""
    ...

async def latest() -> list[dict]:
    """抓全部來源最新新聞 — 排程推播用"""
    ...

if __name__ == "__main__":
    # CLI 入口 — Agent 透過 shell 執行
    args = sys.argv[1:]
    if "--all" in args:
        result = asyncio.run(latest())
    else:
        symbol = args[0] if args else None
        limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10
        result = asyncio.run(fetch(symbol, limit))
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

| Job | 頻率 | 流程 |
|-----|------|------|
| 新聞推播 | 每小時 | `fetch_news.latest()` → Agent 摘要 → 推 Telegram |
| Threads 追蹤 | 每 15 分鐘 | `fetch_threads.check_new()` → 直接推 Telegram |

### 推播流程

```
新聞：
  排程觸發 → fetch_news.latest() → 拿到新文章
  → 過濾已推 URL → AgentBridge.send("摘要以下新聞：{json}")
  → 推給訂閱者

Threads：
  排程觸發 → fetch_threads.check_new() → 拿到新貼文
  → 過濾已推 ID → 格式化 → 直接推給訂閱者
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
├── pushed_threads.json     # 已推 Threads ID（保留 3 天）
└── logs/                   # log 檔案
```

### subscriptions.json 結構

```json
{
  "news": [{"chat_id": 123456, "subscribed_at": "2026-08-22T03:00:00"}],
  "threads": [{"chat_id": 123456, "subscribed_at": "2026-08-22T03:00:00"}]
}
```

### pushed_news.json 結構

```json
[
  {"url": "https://...", "pushed_at": "2026-08-22T03:00:00"},
  ...
]
```

### TTL 清理

- 新聞已推 URL：保留 **7 天**
- Threads 已推 ID：保留 **3 天**
- 排程 job 執行時順便清理過期資料

### Agent 不存取資料層

Agent 只透過 tool script 拿即時資料，不碰 `data/` 目錄。

## 8. 新聞來源（15 個）

| # | 來源 | 格式 |
|---|------|------|
| 1 | CNYES 鉅亨網 | JSON API |
| 2 | MoneyDJ | RSS |
| 3 | Yahoo 股市 | RSS |
| 4 | UDN 聯合新聞網（財經版） | RSS |
| 5 | UAnalyze | HTML |
| 6 | Fugle | HTML |
| 7 | Vocus 方格子（特定作者） | Next.js SSR |
| 8 | MacroMicro 財經M平方 | RSS (morss) |
| 9 | FinGuider | JSON API |
| 10 | Fintastic | RSS (morss) |
| 11 | Forecastock | RSS (morss) |
| 12 | NewsDigest AI | RSS |
| 13 | SinoTrade 永豐 | GraphQL |
| 14 | Pocket 學堂 | JSON API |
| 15 | Buffett Letters + Howard Marks Memos | PDF/HTML |

**已砍：** Google News TW（雜訊多）

## 9. Threads 追蹤

| 項目 | 決定 |
|------|------|
| 技術方案 | **Threads 官方 API**（取代 Playwright） |
| 認證 | Meta Developer App + long-lived access token |
| 端點 | `GET /{user_id}/threads` |
| 好處 | 不需 chromium、穩定、Docker image 小 |

## 10. 部署

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
│   ├── handlers.py         # Telegram message handlers
│   ├── scheduler.py        # APScheduler jobs
│   └── subscriptions.py    # /sub_* /unsub_* 管理
├── agent/
│   ├── bridge.py           # AgentBridge ABC + AntigravityCLIBridge
│   └── prompts.py          # Agent prompt templates
├── tools/
│   ├── fetch_news.py
│   ├── uanalyze.py
│   ├── get_stock_price.py
│   ├── draw_kchart.py
│   ├── fetch_threads.py
│   └── summarize_document.py
├── data/
│   ├── subscriptions.json
│   ├── pushed_news.json
│   ├── pushed_threads.json
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

# Threads
THREADS_ACCESS_TOKEN=xxx
```

### 應用設定（`config.json` 或 code default）

```json
{
  "vocus_users": ["@ieobserve", "@miula", "65ab564cfd897800018a88cc"],
  "uanalyze_keywords": ["AI", "半導體", "ETF"],
  "enable_udn_news": true,
  "enable_yahoo_news": true,
  "news_schedule_interval_min": 60,
  "threads_schedule_interval_min": 15
}
```

## 11. 監控 / Logging

| 層級 | 輸出 |
|------|------|
| DEBUG / INFO | stdout（`docker logs` 看） |
| WARNING / ERROR | stdout + `data/logs/bot.log`（rotation） |
| CRITICAL（連續失敗） | 推 Telegram 通知管理者 |

## 12. 未來升級路徑

| 條件 | 動作 |
|------|------|
| 取得 `GEMINI_API_KEY` | 加 `AntigravitySDKBridge`，呼叫端不改 |
| 換 AI 框架 | 新增 `XxxBridge` 實作 `AgentBridge` ABC |
| 需要多輪對話 | 在 Bridge 加 `conversation_id` 參數 |
| 需要 DB | 把 JSON 換成 SQLite，data layer 獨立模組 |

## 13. Out of Scope

- Web 儀表板
- 情緒分析
- 每日自動分析 + 低估偵測
- MEGA 下載
- Podcast 摘要
- /chat AI 對話（由 @agent 取代）
- 自選股管理
- 爆量偵測（已移除）
