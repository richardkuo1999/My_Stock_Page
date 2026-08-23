# 05 — `/data` 補供應鏈(A7) + 訂單能見度(A8)

**What to build:** `/data` 選單新增「供應鏈」（同業/供應鏈對照標的清單）與「訂單能見度」（訂單能見度 + 合約負債）。訂單能見度資料稀疏，該股無資料時回清楚的「查無訂單能見度資料」提示。

**Blocked by:** 04（選單骨架先建好）。

**Status:** DONE

- [x] `/data` 選單多「供應鏈」「訂單能見度」兩項，各回對應資料
- [x] A8 無資料時回「查無訂單能見度資料」，非空白/錯誤
- [x] 純資料不呼叫 AI
- [x] Agent 支援：CLI 帶參數回摘要 JSON；`agent/prompts.py` data 工具說明補這兩項
- [x] 文件同步：README、ARCHITECTURE、`HELP_TEXT`（若涉及）、map/ticket 狀態
- [x] `tests/test_uanalyze.py` + `tests/test_handlers.py`（含 A8 無資料提示）；全套測試綠
