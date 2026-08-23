# 03 — `/p` 疊加 UAnalyze 基本面（best-effort）

**What to build:** `/p <代號>` 保留現有 Fugle/FinMind 價量（秒回），再 best-effort 補打 UAnalyze 基本面指標（本益比、殖利率等，gidp `WebStockInfo`）附在同一則訊息。UAnalyze 逾時/失敗則略過，價量照常秒回、不被拖累。

**Blocked by:** 01（用 gidp helper）。

**Status:** ready-for-agent

- [ ] `/p 2330` 回價量 + UAnalyze 基本面；UAnalyze 失敗時價量仍正常回（形態 a1）
- [ ] 基本面抓取為純資料，不呼叫 AI
- [ ] Agent 支援：`get_stock_price` CLI 預設輸出**摘要 JSON 含基本面**；`agent/prompts.py` 工具 1 說明更新（註明含基本面、best-effort）
- [ ] 文件同步：README 指令表（/p 說明加基本面）、ARCHITECTURE、`HELP_TEXT`、map/ticket 狀態
- [ ] `tests/test_stock_price.py` + `tests/test_handlers.py`：斷言 UAnalyze 失敗時 `/p` 仍回價量；全套測試綠
