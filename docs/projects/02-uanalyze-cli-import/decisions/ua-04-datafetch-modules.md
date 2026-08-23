# 群3：data_fetch 模組群 是否引入與形態

<!-- labels: wayfinder:grilling -->
<!-- parent: map-uanalyze-cli -->
<!-- blocked-by: ua-02-auth-decision -->
<!-- blocks: ua-05-dcf -->

**Type:** grilling (HITL)
**Status:** ✅ closed（2026-08-22，assignee: agent）

## Resolution — 群3 data_fetch 模組群

6 個功能全部實測 200 回真資料（詳見 findings 未列，決策當下打過）。決策：

- **A3 法人共識** → **引入**，進 `/data` 選單。⚠️跨兩 domain：單季 EPS 追蹤走 cronjob(B) `EPSTrackingActualVSForecastModule`；月營收/年營收共識走 gidp(C) `MonthlyRevenueTrackingConcensuslModule`/`EPSRevenueConsensusEstimate`。
- **A4 每股估值指標** → **引入**，進 `/data` 選單。cronjob(B) `PerShareValueForValuationModel`（多年份表格：每股自由現金流等）。
  - **選單標籤正名為「財務指標」**（非「每股估值」，也不用「每股」前綴）：實測回傳是「每股基礎財務指標的歷年時間序列」共 10 個指標（每股自由現金流/EPS/本業EPS/現金股息/研發調整EPS/每股EBITDA/本業EBITDA/年度ROE/年度ROIC）× 14 年（D2012–D2025/26），**不是估值結論**，叫「估值」會與同選單的 DCF（真估值）混淆。
  - **呈現 = 只給近 4–5 年**（最新趨勢，Telegram 訊息精簡；不全倒 140 格）。
- **A7 供應鏈** → **引入**，進 `/data` 選單。cronjob(B) `StockComparisonStockPool`（回同業代號清單如 `["2303","5347","6770"]`，輕量好呈現）。
- **A8 訂單能見度** → **引入**，進 `/data` 選單。cronjob(B) `OrderVisibilityModule`+`ContractLiabilityModule`。⚠️資料稀疏（2330 實測回空 `{"country":"TW"}`）→ **無資料時回「查無訂單能見度資料」**。
- **A6 河流圖/PE-PB Band** → **不引入**。理由：來源只回數據序列、無畫圖；要做成圖片（比照 `/k`）需自己畫，實作成本高、增量有限。
- **A9 即時基本面** → **併進現有 `/p`**（不進 `/data` 選單）。查證：現有 `/p`（Fugle/FinMind）只回 price/change/change_pct/volume，**無基本面指標**，A9（gidp `WebStockInfo`：收盤價+本益比/殖利率等）是真增量。
  - **形態 a1（best-effort 加分）**：`/p` 保留 Fugle 價量秒回，**再補打** UAnalyze WebStockInfo 附基本面；UAnalyze 逾時/失敗則**略過不影響 `/p`**。保住 `/p` 快捷指令的速度與可靠。

## 統一形態

- 新增快捷指令 **`/data <代號>`**：仿 `/ua` 選單模式 → 選代號 → 選項目（法人共識 / 每股估值 / 供應鏈 / 訂單能見度）→ 回結果。4 個 data_fetch 項目包在一起。
- A3/A4/A7/A8 資料是「圖表用多維 series」→ 實作時需濃縮成 Telegram 文字可讀形式（非直接倒 JSON）。

## 待實作接口（給 spec）

- `tools/uanalyze.py`：擴充 `UAnalyzeAuth`（ua-02 決策）+ 新增純資料函式群（`fetch_eps_consensus`/`fetch_per_share_valuation`/`fetch_supply_chain`/`fetch_order_visibility`/`fetch_stock_fundamentals`），皆純資料不呼叫 AI。
- `bot/`：新增 `/data` 指令 + 選單 callback（比照 `/ua`）；`/p` 疊加 best-effort 基本面。

## Question

這批功能涉及 session cookie（cronjob）與 GIDP token（gidp）兩套認證（見 ua-02 決策）。逐一決定是否引入、及形態（Telegram 指令 / Agent 工具 / 不引入）：

- **A3 法人預估共識追蹤** — ⚠️**跨兩套 domain**：單季 EPS 追蹤走 cronjob(B) `EPSTrackingActualVSForecastModule`；月營收追蹤 + 年營收/EPS 共識走 gidp(C) `MonthlyRevenueTrackingConcensuslModule` / `EPSRevenueConsensusEstimate`
- **A4 折現估值與每股指標**（PerShareValuation）— cronjob(B) `PerShareValueForValuationModel`
- **A6 股票評價河流圖 + 歷史 PE/PB**（Stock Valuation）— cronjob(B) `HistoricalPer/Pbr` + `PE_Band/PB_Band`；注意河流圖是**圖**，可能要比照 `/k` 產圖片
- **A7 同業與上下游供應鏈標的**（Supply Chain）— cronjob(B) `StockComparisonStockPool`
- **A8 訂單能見度與合約負債追蹤**（Order Visibility）— cronjob(B) `OrderVisibilityModule` + `ContractLiabilityModule`
- **A9 即時基本面與收盤價**（WebStockInfo）— gidp(C) `WebStockInfo`；注意與現有 `/p` 股價可能重疊

**認證已由 ua-02 解決**（cronjob 用 4-cookie+Origin、gidp 用 GIDP 常數）。每個功能形態可不同。A6 涉及畫圖、A9 與現有 `/p` 重疊需釐清、A3 跨兩 domain。

**來源檔案：** `uanalyze_cli/get_eps.py` `fetch_*` 函式群（line 318–415）
