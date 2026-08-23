# 排程與推播架構

<!-- labels: wayfinder:grilling -->
<!-- parent: map -->
<!-- blocked-by: (none — unblocked) -->
<!-- assigned: kiro -->
<!-- status: closed -->

## Question

新聞推播、Threads 追蹤的排程機制怎麼設計？

需要決定：
1. **排程器選型**：APScheduler（沿用）？Celery？簡單 cron？systemd timer？
2. **Process 架構**：排程器跟 Bot 同 process 還是獨立 process？（舊版是同一個 FastAPI app 裡）
3. **推播內容**：排程 job 直接推 Telegram（純 Python），還是推播前先過 Agent 做 summarize？
4. **失敗處理**：job 失敗了怎麼辦？retry？alert？
5. **頻率設計**：各排程的觸發頻率（沿用舊版還是重新定義）

## Resolution

### 排程器：APScheduler（沿用）

- 輕量，同 process 跑
- 不需要 Redis/broker
- 支援動態新增/移除 job（用戶 `/sub_*` `/unsub_*`）

### Process 架構：同 process

```
一個 Python process
├── Telegram Bot (python-telegram-bot, polling/webhook)
├── APScheduler (排程 job)
└── tools/ (被兩者共用 import)
```

- 簡單，一個 process 管理
- 排程 job 直接拿 bot instance 送訊息
- Agent call 用 `asyncio.create_subprocess_exec`，非同步不阻塞 event loop
- 多個用戶同時使用不互相干擾

### 推播流程

| 推播類型 | 流程 |
|----------|------|
| Threads | 排程 → `fetch_threads.check_new()` → Bot 格式化 → 直接推 Telegram |
| 新聞 | 排程 → `fetch_news.latest()` → **經 Agent 摘要**（`agy -p "摘要：{json}"`）→ 推 Telegram |

### 失敗處理：retry + 通知管理者

- 失敗自動 retry 1-2 次
- 連續失敗 → 推訊息通知管理者（admin chat_id）
- 所有失敗寫 log

### 排程頻率

| Job | 頻率 |
|-----|------|
| 新聞推播 | 每小時一次 |
| Threads 追蹤 | 每 15 分鐘 |

用戶可透過 `/sub_*` `/unsub_*` 管理訂閱。

### 決定移除的功能

- **爆量偵測**：整個功能移除（包括 `check_volume_spike.py` tool）
