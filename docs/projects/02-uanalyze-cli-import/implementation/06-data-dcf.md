# 06 — `/data` 補 DCF 估值(A5)

**What to build:** `/data` 選單新增「DCF 估值」，回時間加權動態 DCF 的關鍵數字：每股合理內在價值、1 年後前瞻合理價值、營收動能、時間加權基期。純計算（WACC、時間權重對齊、roll-forward `V1=V0*(1+WACC)-EPS`）移入工具，走 `only_dcf` 等價路徑——**不呼叫 AI**（來源的近況/利多/利空 AI 欄位與現有 `/ua` 重複，不搬）。

**Blocked by:** 04（選單骨架；且 DCF 吃 A3/A4 資料）。

**Status:** DONE

- [x] `/data` 選單多「DCF 估值」，回內在價值/前瞻價值/營收動能/時間加權基期
- [x] DCF 計算為純函式，不呼叫 AI；EPS 資料不足時回清楚提示
- [x] Agent 支援：CLI 帶參數（如 `--dcf`）回**估值關鍵數字摘要 JSON**；`agent/prompts.py` 補說明
- [x] 文件同步：README、ARCHITECTURE、`HELP_TEXT`（若涉及）、map/ticket 狀態
- [x] `tests/test_uanalyze.py`：DCF 純計算以「EPS 輸入→內在價值輸出」斷言（最好測的純函式）；全套測試綠
