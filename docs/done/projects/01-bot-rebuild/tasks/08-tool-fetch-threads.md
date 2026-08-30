# 08 — Tool: fetch_threads（Threads API）

**What to build:** `tools/fetch_threads.py` — 用 Threads 官方 API 抓追蹤帳號的最新貼文，回傳 JSON。全新撰寫（取代舊版 Playwright 爬蟲）。

**Blocked by:** 01 — 專案骨架 + Bot 啟動

**Status:** done

- [x] `python tools/fetch_threads.py --check-new` 回傳新貼文 JSON
- [x] `from tools.fetch_threads import check_new` 可直接 import 使用
- [x] 使用 Threads API `GET /{user_id}/threads` 端點
- [x] 帶 `Authorization: Bearer {THREADS_ACCESS_TOKEN}` header
- [x] 回傳格式：`{"posts": [{id, user, text, timestamp, url}]}`
- [x] token 失效時回傳明確錯誤（提示需要 refresh）
- [x] 檔頭 docstring 符合規範
- [x] 有 unit test（mock API response）
