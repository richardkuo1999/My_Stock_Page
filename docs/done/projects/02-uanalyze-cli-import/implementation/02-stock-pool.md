# 02 — 股名對照表換 StockPool 全表

**What to build:** 用 UAnalyze 官方全台股名對照（gidp `StockPool`，~12,361 檔 `{stock_code, stock_name}`）取代現有 seed-20 + Agent 自成長機制。使用者查任何代號（`/p`、`/ua`、`/data`、個股新聞過濾）時公司名對照涵蓋幾乎全台股。

**Blocked by:** 01（用 gidp helper）。

**Status:** DONE

- [x] 新增 `fetch_stock_pool()`（gidp `StockPool?country=TW`）回全表
- [x] 啟動/首次查詢灌入本地表（`data/stock_names.json` 或記憶體）→ 之後查本地；定期刷新（如每週）
- [x] Agent 自成長「主路徑」退役；**保留 `lookup_stock_name --set` 手動寫回當後備**
- [x] `lookup_stock_name` / `fetch_news` 個股過濾介面不變，換源後回歸測試通過
- [x] Agent 支援：`lookup_stock_name` CLI 查詢照舊（`agent/prompts.py` 工具 7 已描述，如語意有變則同步）
- [x] 文件同步：README（stock_names 說明由「seed 20 自成長」改為「全表」）、ARCHITECTURE、`HELP_TEXT`（若涉及）、map/ticket 狀態
- [x] `tests/test_lookup_stock_name.py` 更新；全套測試綠
