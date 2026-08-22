# 02 — 訂閱管理（/sub_* /unsub_*）

**What to build:** 用戶可在 Telegram 中使用 `/sub_news`、`/unsub_news`、`/sub_threads`、`/unsub_threads` 管理推播訂閱。訂閱狀態持久化到 `data/subscriptions.json`。

**Blocked by:** 01 — 專案骨架 + Bot 啟動

**Status:** done

- [x] `/sub_news` 將用戶 chat_id 加入新聞訂閱清單，回覆確認訊息
- [x] `/unsub_news` 將用戶從新聞訂閱清單移除，回覆確認訊息
- [x] `/sub_threads` 將用戶 chat_id 加入 Threads 訂閱清單，回覆確認訊息
- [x] `/unsub_threads` 將用戶從 Threads 訂閱清單移除，回覆確認訊息
- [x] 重複訂閱不會產生重複紀錄
- [x] 訂閱狀態寫入 `data/subscriptions.json`，重啟後不遺失
- [x] 有 unit test 驗證訂閱邏輯
