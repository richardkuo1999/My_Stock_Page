# 03 — `/p` 疊加 UAnalyze 基本面（best-effort）

**What to build:** `/p <代號>` 保留現有 Fugle/FinMind 價量（秒回），再 best-effort 補打 UAnalyze 基本面指標（本益比、殖利率等，gidp `WebStockInfo`）附在同一則訊息。UAnalyze 逾時/失敗則略過，價量照常秒回、不被拖累。

**Blocked by:** 01（用 gidp helper）。

**Status:** DONE

**實打 findings（2026-08-23）：** ticket 假設 `WebStockInfo` 帶本益比/殖利率，但真實打
`gidp WebStockInfo/2330?country=TW` 只回 12 個 ChineseAccount（收盤價 / 當日漲跌幅 / 最新漲停跌停判斷 /
收盤價日期 / 最新股本 / 最新財報 / 月營收 / 法說會 / 統計期間 / 逐字稿 / 掛牌類別 / 股票分類），
**無本益比、無殖利率、無股價淨值比**。本益比另從同 domain（gidp）`HistoricalPer` 月序列取最新一個月補上
（實打 2330 最新 202608=27.9）。殖利率 gidp 無對應端點（DividendYield/HistoricalYield… 皆 404），故不列。
最終 `/p` 疊加：收盤價 / 當日漲跌幅(%) / 最新財報 / 最新月營收 / 掛牌類別 / 本益比。

- [x] `/p 2330` 回價量 + UAnalyze 基本面；UAnalyze 失敗時價量仍正常回（形態 a1）
- [x] 基本面抓取為純資料，不呼叫 AI
- [x] Agent 支援：`get_stock_price` CLI 預設輸出**摘要 JSON 含基本面**；`agent/prompts.py` 工具 1 說明更新（註明含基本面、best-effort）
- [x] 文件同步：README 指令表（/p 說明加基本面）、ARCHITECTURE、`HELP_TEXT`、map/ticket 狀態
- [x] `tests/test_stock_price.py` + `tests/test_handlers.py`：斷言 UAnalyze 失敗時 `/p` 仍回價量；全套測試綠
