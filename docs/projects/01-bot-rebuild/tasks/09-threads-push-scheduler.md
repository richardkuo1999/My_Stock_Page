# 09 — Threads 排程推播

**What to build:** APScheduler 每 15 分鐘觸發 Threads 推播 job：抓新貼文 → 過濾已推 ID → 格式化 → 直接推給訂閱者（不經 Agent）。含 `pushed_threads.json` 管理和 3 天 TTL 清理。

**Blocked by:** 02 — 訂閱管理, 08 — Tool: fetch_threads

**Status:** done

- [x] APScheduler job 每 15 分鐘觸發一次
- [x] 呼叫 `fetch_threads.check_new()` 取得新貼文
- [x] 以 post ID 為 key 比對 `pushed_threads.json`，過濾已推送的
- [x] 新貼文格式化後直接推給所有 Threads 訂閱者（不經 Agent）
- [x] 推送後將 ID + 時間戳寫入 `pushed_threads.json`
- [x] 每次 job 執行時清理超過 3 天的舊紀錄
- [x] 有 unit test
