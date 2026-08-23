# 07 — 新聞排程推播

**What to build:** APScheduler 每小時觸發新聞推播 job：抓新聞 → 過濾已推 URL → 經 Agent 摘要 → 推給訂閱者。含 `pushed_news.json` 管理和 7 天 TTL 清理。

**Blocked by:** 02 — 訂閱管理, 03 — AgentBridge, 06 — Tool: fetch_news

**Status:** done

- [x] APScheduler job 每小時觸發一次
- [x] 呼叫 `fetch_news.latest()` 取得新文章
- [x] 以 URL 為 key 比對 `pushed_news.json`，過濾已推送的
- [x] 新文章經 `AgentBridge.send()` 產出摘要
- [x] 摘要推送給所有新聞訂閱者
- [x] 推送後將 URL + 時間戳寫入 `pushed_news.json`
- [x] 每次 job 執行時清理超過 7 天的舊紀錄
- [x] 模糊標題去重（避免同篇文章不同 URL）
- [x] 有 unit test
