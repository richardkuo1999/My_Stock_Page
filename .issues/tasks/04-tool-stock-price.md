# 04 — Tool: get_stock_price

**What to build:** `tools/get_stock_price.py` — 查詢即時/收盤股價，CLI 回傳 JSON，也可被 Bot import 使用。從舊版 `price_fetcher.py` + `finmind_fetcher.py` 搬移並精簡邏輯。

**Blocked by:** 01 — 專案骨架 + Bot 啟動

**Status:** ready-for-agent

- [ ] `python tools/get_stock_price.py 2330` 回傳 JSON（含 symbol、price、change、volume 等）
- [ ] `from tools.get_stock_price import fetch_price` 可直接 import 使用
- [ ] 支援 FinMind token 輪替（多組 token）
- [ ] 支援 Fugle API 作為即時股價來源
- [ ] 找不到代號時回傳 `{"error": "..."}` + 非零 exit code
- [ ] 檔頭 docstring 符合 ARCHITECTURE.md 規範
- [ ] 有 unit test
