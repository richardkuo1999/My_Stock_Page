# 04 — Tool: get_stock_price

**What to build:** `tools/get_stock_price.py` — 查詢即時/收盤股價，CLI 回傳 JSON，也可被 Bot import 使用。從舊版 `price_fetcher.py` + `finmind_fetcher.py` 搬移並精簡邏輯。

**Blocked by:** 01 — 專案骨架 + Bot 啟動

**Status:** done

- [x] `python tools/get_stock_price.py 2330` 回傳 JSON（含 symbol、price、change、volume 等）
- [x] `from tools.get_stock_price import fetch_price` 可直接 import 使用
- [x] 支援 FinMind token 輪替（多組 token）
- [x] 支援 Fugle API 作為即時股價來源
- [x] 找不到代號時回傳 `{"error": "..."}` + 非零 exit code
- [x] 檔頭 docstring 符合 ARCHITECTURE.md 規範
- [x] 有 unit test
