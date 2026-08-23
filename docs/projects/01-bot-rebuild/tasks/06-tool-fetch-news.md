# 06 — Tool: fetch_news

**What to build:** `tools/fetch_news.py` — 從 15 個來源抓新聞，回傳 JSON。從舊版 `news_parser.py` 搬移邏輯，砍掉 Google News。支援指定股票或全部最新。

**Blocked by:** 01 — 專案骨架 + Bot 啟動

**Status:** done

- [x] `python tools/fetch_news.py 2330 --limit 5` 回傳指定股票相關新聞 JSON
- [x] `python tools/fetch_news.py --all` 回傳全部來源最新新聞 JSON
- [x] `from tools.fetch_news import fetch, latest` 可直接 import 使用
- [x] 支援 15 個新聞來源（含 Vocus 特定作者、morss proxy 來源）
- [x] 並行抓取（`asyncio.gather`）
- [x] 回傳格式：`{"articles": [{title, source, date, url, summary}]}`
- [x] 檔頭 docstring 符合規範
- [x] 有 unit test（mock HTTP，驗證各 parser）
