# 07 — `/ua` 法說會逐字稿全文 + 分頁快取

**What to build:** `/ua <代號>` 面向選單新增「法說會逐字稿」。選它 → 列該股歷次法說會日期清單 → 選一場 → 顯示**完整逐字稿全文**，用「上一頁/下一頁」按鈕分頁閱讀。取法兩步：gidp `WebStockInfo` 取逐字稿清單（日期+id）→ cronjob `TranscriptDetail?id={id}&country=TWN` 取全文。

**Blocked by:** 01（清單走 gidp、全文走 cronjob cookie）。

**Status:** DONE

- [x] `/ua` 選單多「法說會逐字稿」→ 列日期 → 選一場 → 顯示全文
- [x] 全文分頁（做法 2）：選定某場**打一次** TranscriptDetail → 存**記憶體快取（TTL）**→ 上/下頁用 `edit_message` 換頁、只讀快取切段落，**翻頁不再打 API**（測試斷言 API 只被呼叫一次）
- [x] 純資料不呼叫 AI
- [x] Agent 支援：CLI 帶參數（`--transcript <代號> [id 或 date]`）回**逐字稿摘要/重點 JSON**（Agent 不需 16K 全文）；`agent/prompts.py` 補說明（回摘要）
- [x] 文件同步：README、ARCHITECTURE、`HELP_TEXT`、map/ticket 狀態
- [x] `tests/test_uanalyze.py` + `tests/test_handlers.py`（分頁翻頁不重打 API）；全套測試綠
