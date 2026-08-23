# A5 時間加權動態 DCF 估值 是否引入與形態

<!-- labels: wayfinder:grilling -->
<!-- parent: map-uanalyze-cli -->
<!-- blocked-by: ua-04-datafetch-modules -->

**Type:** grilling (HITL)
**Status:** ✅ closed（2026-08-23，assignee: agent）

## Resolution — A5 時間加權動態 DCF 估值

- **引入 A5 DCF** ✅（估值是投資核心，有價值）。
- **AI 質化欄位不搬（走 `only_dcf=True` 純數字路徑）**：`dcf_valuation_calculator.py` 的 `calculate_stock_dcf` 有兩條路徑——`only_dcf=True` 只抓數據 + 算 DCF（不呼叫 AI），`only_dcf=False` 額外併發打 `_fetch_ai_prompt("近況發展"/"利多因素"/"利空因素")` 呼叫 AI completion。**採 `only_dcf=True`**：符合「工具不呼叫 AI」鐵則，且那三個 AI 欄位**與現有 `/ua` 重複**（查證 `bot/handlers.py` UA_PROMPTS line 36/42/43 已有同名「近況發展/利多因素/利空因素」三面向）。使用者要質化分析用 `/ua` 即可。
- **形態 = 併進 `/data` 選單第 5 項**：不開獨立 `/dcf` 指令。`/data <代號>` 選單目前 4 項（法人共識/每股估值/供應鏈/訂單能見度，見 ua-04）+ DCF = 5 項。
- **不做 CSV 匯出**：`batch_dcf_valuation_to_csv` 批次形態不進 bot（Telegram 單檔互動不需要；批次離線分析保留為獨立 CLI 即可）。

## 純計算部分可直接搬（確定性）

- `_compute_dcf`（WACC、時間權重對齊、動態年份適應）、`_compute_broker_eps_medians`、1-Year roll-forward（`V1 = V0*(1+WACC) - EPS_2026`）皆為純數學，可原樣移入工具。
- DCF 吃的資料 `_fetch_revenue_tracking`/`_fetch_eps_consensus`/`_fetch_stock_category` = ua-04 已引入的 A3/A4 data_fetch，複用同一組 `UAnalyzeAuth`（ua-02）。

## 待實作接口（給 spec）

- `tools/uanalyze.py`：新增純資料+計算函式（如 `compute_dcf_valuation(stock)` 回關鍵數字：每股合理內在價值、1年後前瞻價值、營收動能、時間加權基期等），內部只走 `only_dcf` 等價邏輯，不呼叫 AI。
- `bot/`：`/data` 選單加第 5 項「DCF 估值」callback 分支。

## Question

決定重運算功能 A5 是否引入、及形態：

- **A5 時間加權動態 DCF 估值模型 + CSV 匯出** — `dcf_valuation_calculator.py`（~20KB，含 `calculate_stock_dcf`、`batch_dcf_valuation_to_csv`）
- 時間權重對齊（8 月權重）、動態年份適應（2026E–2029E）、當前營收動能、17 參數精簡 CSV 輸出

**與現有的張力：**
- 重運算、耗時 → 觸發形態（快捷指令會卡？走 `@mention`？背景 job？）
- 吃群3（A3/A4）的資料再算 → 依賴群3的引入決策
- CSV 匯出形態在 Telegram 怎麼交付（傳檔案？只回關鍵數字？）
- `_fetch_ai_prompt` 內部呼叫 AI completion → 與「工具不呼叫 AI」鐵則衝突，需拆解

**來源檔案：** `uanalyze_cli/dcf_valuation_calculator.py`
