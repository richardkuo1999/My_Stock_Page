# 03 — tools/ 重構：raw（純取數）/ analysis（功能）分層

## 背景與動機

專案已轉為 **Agent 驅動**（`/ua` `/data` `/news` 互動選單已移除，改由 `/ask` 統一入口）。
現況 `tools/` 下工具把「取數」與「加工組合」混在同一支甚至同一 function，導致：

- `uanalyze.py` 有 **5 組同端點被多個 function 重複打**（各取所需、各打各的）：
  `EPSRevenueConsensusEstimate`、`MonthlyRevenueTrackingConcensuslModule`、
  `HistoricalPer`、`report-summaries`、`WebStockInfo`。
- `fetch_eps_consensus` 一支就湊了 4 個端點 + 兩種認證（cookie + gidp）。
- 同端點在不同 function 用不同 domain（`HistoricalPer`：一支 gidp 拿 117 筆、一支 cronjob 拿 237 筆——**實測資料不同，cronjob 是超集**）。

## 目標架構

整個 `tools/` 採 **兩層 + 資料夾分離**：

```
tools/
├── raw/               # 純資料抓取層
│   ├── uanalyze.py    #   一端點一 function，只抓原始資料、回最完整結構，不判讀/不組合
│   ├── finmind.py
│   ├── fugle.py
│   ├── cnyes.py
│   └── yfinance.py
├── analysis/          # 功能層：call raw 層做組合 / 計算 / 判讀 / 繪圖
│   ├── valuation.py   #   估值計算（DCF / PE-PB 河流圖 / 五線譜 / 目標價彙整）
│   ├── stock_price.py #   即時股價（疊 UAnalyze 基本面）
│   ├── news.py        #   15 來源新聞聚合 + 個股過濾 + 單篇全文
│   ├── charts.py      #   K 線圖 / 盤中分時圖
│   ├── reports.py     #   券商研究報告
│   └── documents.py   #   URL/PDF 摘要（唯一呼叫 AI 的 analysis）
└── lookup_stock_name.py   # 資料工具（代號↔名，純本地，不歸兩層）
```

### 分層判準

- **raw 層**：一個「資料源端點」對一個 function。只抓、回最完整原始資料。**不跨端點組合、不判讀、不計算**。
  認證固定（該端點唯一正確的 domain/認證）。皆回原始 dict/list（含 `{"error"}`）。
  **AI 類端點（/completions、/chat）也歸 raw**——判準是「呼叫外部 API 就是取數」，那個 API 內部是不是 AI 與分層無關。
- **analysis 層**：`import` raw 層 function，做組合/計算/判讀/繪圖。是 bot 確定性路徑與 Agent 的消費對象。
  analysis 本身不呼叫外部 AI（若需 AI 判讀，是 Agent 的事）。

### 組合型 feature 的去留判準（重要）

現況 uanalyze 裡的「組合多端點」function 依「組合複雜度 + 消費者」決定去留：

| 類型 | 例 | 去向 |
|------|-----|------|
| 有真正計算 | DCF 折現、PE/PB Band 百分位、SmartEstimate 高低值整理 | **保留成 analysis function**（放 `analysis/valuation.py` 等） |
| 有非 Agent 消費者 | `fetch_stock_fundamentals`（`/p` 疊加）、`list_latest_reports`（排程推播） | **保留成 analysis function** |
| 純並排/挑欄位、只 Agent 用 | `fetch_eps_consensus` 組年度表、`fetch_peers_comparison` | **廢除**，改由 Agent 自己 call raw 層組合（README 教怎麼組） |

> 原則：計算歸 analysis 計算層、純取數歸 raw、純並排交 Agent。

## uanalyze raw fetcher 清單（試點目標）

一端點一 raw function（命名 `fetch_raw_<語意>`）。認證欄「待驗」者於試點時逐一實打確認。

| raw function | 端點 | domain/認證 | 能取到什麼 |
|--------------|------|-------------|-----------|
| `fetch_raw_eps_revenue_consensus` | EPSRevenueConsensusEstimate | gidp+country=TW | 年度 營收(ua50189)/EPS(ua50187)/本業EPS(ua50209)，含 (f) 預估年 |
| `fetch_raw_revenue_tracking` | MonthlyRevenueTrackingConcensuslModule | gidp | 月營收共識/累計/超預期%(ua70306…) |
| `fetch_raw_broker_eps_table` | EPSFilterTableE0001 | gidp | 全市場各券商逐年預估 EPS（需以 stock_code 過濾） |
| `fetch_raw_eps_tracking` | EPSTrackingActualVSForecastModule | cronjob | 單季 實際EPS vs 法人共識 |
| `fetch_raw_historical_per` | HistoricalPer | **cronjob**（237 筆超集，非 gidp 117 筆） | 本益比月序列（近20年） |
| `fetch_raw_historical_pbr` | HistoricalPbr | cronjob | 股價淨值比月序列 |
| `fetch_raw_pe_band` | PE_Band | cronjob | refdata 同業本益比中位數 |
| `fetch_raw_per_share_value` | PerShareValueForValuationModel | cronjob | 每股 FCF/EPS/ROE/ROIC…近年 |
| `fetch_raw_stock_comparison_pool` | StockComparisonStockPool | cronjob | 同業/供應鏈代號清單 |
| `fetch_raw_institutional_net` | InstitutionalInvestorsNet | cronjob | 三大法人買賣超 |
| `fetch_raw_profit_margins` | MajorProfitMargins | cronjob | 毛利率/營益率/淨利率 |
| `fetch_raw_cash_flow_trend` | CashFlowTrend | cronjob | 營業/投資/籌資/自由現金流 |
| `fetch_raw_cash_dividend_payout` | CashDividendPayoutRatio | cronjob | 現金股息/發放率 |
| `fetch_raw_margin_balance` | MarginBalanceVSMarginUtilization | cronjob | 融資餘額/使用率 |
| `fetch_raw_short_interest` | ShortInterestVSShortSellUtilization | cronjob | 融券餘額/使用率 |
| `fetch_raw_major_investors_holdings` | MajorInvestorsHoldings | cronjob | 外資/董監持股比率 |
| `fetch_raw_shareholders_stats` | ShareHoldersStatistics | cronjob | 股東人數/大戶比率 |
| `fetch_raw_order_visibility` | OrderVisibilitySingleRankings | gidp | 訂單能見度+合約負債（全市場過濾本檔） |
| `fetch_raw_web_stock_info` | WebStockInfo | gidp | 收盤/漲跌幅/最新財報/月營收/掛牌類別/逐字稿清單 |
| `fetch_raw_transcript_detail` | TranscriptDetail | cronjob | 逐字稿全文 |
| `fetch_raw_report_summaries` | report-summaries | jwt(twobitto) | 研究報告摘要（stock 過濾 或 limit/offset 全站） |
| `fetch_raw_smart_estimate` | ReutersSmartEstimate_*（8） | gidp | 法人預估各指標 平均/最低/最高 |
| `fetch_raw_eps_route` | QEPSRevenueConsensusEstimateRoute | gidp | 未來五季 營收/EPS 路徑 |
| `fetch_raw_margin_route` | QMargingsConsensusEstimateRoute | gidp | 未來五季 毛利率/營益率 路徑 |
| `fetch_raw_rating_trend` | AnalystRatingChangeTrend | gidp | 評等佔比趨勢 |
| `fetch_raw_company_keywords` | company_keywords（POST） | 特殊（僅 Origin/Referer，不帶 token） | 批次雷達多類資料 |
| `fetch_raw_completion` | /completions | jwt | AI 分析（呼叫外部 AI；外部 API 也算取數，歸 raw） |
| `fetch_raw_ai_chat` | /chat/{kb} | jwt SSE | AI 知識庫問答（呼叫外部 AI；歸 raw） |
| `_auth`（UAnalyzeAuth） | /auth/token(+refresh) | — | 登入/刷新（維持現狀，共用） |

> `report-summaries` 的 `get_reports`(單股) 與 `list_latest_reports`(全站) 合併為單一 raw
> fetcher（帶參數區分），消除重複打。

## analysis 層改寫對應（uanalyze 部分）

| analysis function | 位置 | 由哪些 raw 組成 | 備註 |
|-------------------|------|-----------------|------|
| DCF 估值 | `analysis/valuation.py` | eps_revenue_consensus + revenue_tracking + `_compute_dcf` | 從 uanalyze 搬來；計算層本分 |
| PE/PB Band | `analysis/valuation.py` | historical_per + historical_pbr + pe_band + 百分位算法 | 有計算，保留 |
| SmartEstimate 整理 | `analysis/valuation.py` 或 forecast 模組 | smart_estimate(8) | 有高低值整理，保留 |
| 未來路徑+評等 | 同上 | eps_route + margin_route + rating_trend | 保留 |
| 即時基本面（/p 疊加） | `analysis/stock_price.py` | web_stock_info + historical_per(取末筆) | 有非 Agent 消費者，保留 |
| 最新報告清單（推播） | `analysis/reports.py` 或就近 | report_summaries(全站) | 排程消費，保留 |
| ~~法人共識年度表~~ | **廢除（決策 A）** | — | 純並排無計算、僅 Agent CLI 用、無 bot/推播依賴（已確認）；交 Agent call raw 自組 |
| ~~同業多維比較~~ | **廢除（決策 A）** | — | 同上，交 Agent 自組 |

> **推播鏈路（必須保持）**：`scheduler.py` 的 `uanalyze_push_job` 只用 `list_latest_reports`
> → 重構後改 call `fetch_raw_report_summaries`（全站模式）。這是唯一有非 Agent 消費者的
> uanalyze function，raw fetcher 本身即足夠（只取數、不需組合）。新聞推播用 `fetch_news`（另一支）。

## CLI 進入點（決策：甲）

工具移入子資料夾後，CLI 直接跑子路徑：`python tools/raw/uanalyze.py --xxx`、
`python tools/analysis/valuation.py --dcf 2330`。README/agent prompt/docstring 全數更新新路徑。
需處理 `raw/analysis` 內 import：`from tools.raw import uanalyze` / 相對 import + `sys.path` fallback（沿用現有雙入口慣例）。

## dcf_to_csv 併入

`dcf_to_csv.py` 併入 `analysis/valuation.py`，改為 `valuation.py --dcf <代號> --csv`（多檔並行輸出 CSV）。

## 分階段執行計畫（絕不一次全動）

1. **階段 0（試點）**：只做 uanalyze。
   - 建 `tools/raw/uanalyze.py`（全部 raw fetcher，含端點認證定調實打驗證）。
   - 建 `tools/analysis/valuation.py`（搬 DCF + PE/PB Band + `_compute_dcf`；併 dcf_to_csv）。
   - 其餘 uanalyze feature（基本面/報告/前瞻）暫放 `tools/analysis/uanalyze_*.py` 或就近。
   - 廢除純並排 feature。
   - 更新 import（bot/agent/測試）、CLI 路徑、README、docstring。
   - **驗證模式順暢、全測試綠、DCF/推播/`/p` 回歸** 後才進下一階段。
2. **階段 1+**：推廣到 finmind / fugle / cnyes / yfinance（多為純 raw，好切）→ `raw/`。
3. **階段 2**：get_stock_price / draw_* / fetch_news / broker_reports / summarize_document → `analysis/`。
4. **階段 3**：全面更新 `tools/README.md` 工具地圖、agent prompt、ARCHITECTURE。

## 待驗證項（試點時逐一實打）

- 各 raw fetcher 的**唯一正確認證/domain**（尤其現況用 gidp 的，確認 cronjob 是否也可且更完整）。
  - ✅ **HistoricalPer 已驗證**：cronjob 237 筆(2007~)是 gidp 117 筆(2017~)的超集；重疊區僅 6 點小數點級差異（四捨五入），最新值一致。**定調 cronjob**。
- `company_keywords` 的特殊認證（不帶 token）是否穩定。
- 廢除的 feature 是否真的沒有非 Agent 消費者（grep 確認 bot/scheduler 無直接呼叫）。
  - ✅ 已確認：`fetch_eps_consensus`/`fetch_peers_comparison` 僅各自 CLI 分支呼叫，無 bot/scheduler 依賴。

## 驗收

- `raw/` 每端點一 function、無重複打端點；`analysis/` 只 call raw、不直接打 API（AI 分析與 company_keywords 特例除外）。
- 全測試綠；DCF、`/p` 基本面、UAnalyze 報告推播三條確定性路徑回歸正常。
- README/prompt/docstring 反映新結構與 CLI 路徑。

## 完成狀態（2026-09-12）

✅ **已完成並通過全部驗收**（本檔隨此搬入 `docs/done/`）。

- **raw/**：`uanalyze`(28) / `cnyes`(3) / `finmind`(14，含新增 `fetch_tick_snapshot`) / `fugle`(7) /
  `yfinance_data`(8) / `news_sources`(15 源 fetcher) / `broker_reports`。一端點一 function、無重複打端點。
- **analysis/**：`get_stock_price` / `draw_kchart` / `draw_intraday_chart`（全部委派 raw/fugle・raw/finmind，
  不再自打 API）、`news`（聚合，import raw/news_sources）、`valuation`（DCF + PE-PB Band，含 DCF 批次 CSV）、
  `fundamentals` / `forecast` / `reports` / `summarize_document`。直接打 API 者僅 `news`（CNYES 個股補搜）
  與 `summarize_document`（任意 URL/PDF）兩個 spec 允許特例。
- **廢除**：法人共識年度表 / 同業多維比較（純並排，交 Agent 自組，README 有教）。
- **超出原 spec 的收尾**：fetch_news 徹底拆成 raw/news_sources + analysis/news；broker_reports 歸 raw；
  跨平台化（Windows 相容：動態 repo 根、subprocess env、CJK 字型 fallback）；修 B2（Fugle volume）；
  移除已停用的 CNYES `--candles`。
- **驗收結果**：全套件 **429 passed**；三條確定性路徑（/p price 2410 附基本面、DCF 回完整內在價值、
  報告推播 list_latest_reports）真憑證/真網路實跑正常；文件（README / ARCHITECTURE / tools/README /
  agent prompt / 各 docstring）全面反映 raw/analysis 兩層與新 CLI 路徑。
