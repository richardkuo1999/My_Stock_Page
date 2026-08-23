# 資料層設計

<!-- labels: wayfinder:grilling -->
<!-- parent: map -->
<!-- assigned: kiro -->
<!-- status: closed -->

## Question

新專案的資料儲存策略是什麼？

需要決定：
1. **是否需要 DB**：砍掉 Web + 自選股 + 情緒分析後，還有哪些資料需要持久化？
2. **DB 選型**：SQLite 沿用？還是更輕量的方案（JSON file、Redis）？
3. **資料模型**：需要哪些 table/collection？
4. **Agent 需要存取 DB 嗎？** 還是 Agent 只透過 tool 間接取得資料？
5. **Cache 策略**：stock analysis 的 6 小時 TTL 沿用？

## Resolution

### 需要持久化的資料（3 樣）

| 資料 | 用途 |
|------|------|
| 推播訂閱 | 記錄誰訂了新聞、誰訂了 Threads |
| 已推新聞 ID | 避免重複推播 |
| 已推 Threads ID | 避免重複推播 |

不存的：股票分析 cache（每次即時算）

### 儲存方式：JSON 檔案

不用 SQLite、不用 Redis——量極小，JSON 檔案夠用。

```
data/
├── subscriptions.json      # 訂閱資料
├── pushed_news.json        # 已推新聞 ID（保留 3 天）
└── pushed_threads.json     # 已推 Threads ID（保留 3 天）
```

### TTL 清理

- 已推新聞 ID 保留 **7 天**
- 已推 Threads ID 保留 **3 天**
- 超過 TTL 的自動刪除（排程 job 執行時順便清）
- 避免檔案無限膨脹

### Agent 不存取資料層

- 訂閱管理是 Bot 直接處理（`/sub_*`、`/unsub_*`）
- 已推 ID 是排程 job 內部用
- Agent 只透過 tool script 拿即時資料，不碰 `data/` 目錄
