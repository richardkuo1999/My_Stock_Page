# A12 批次 EPS CSV 匯出 是否引入與形態

<!-- labels: wayfinder:grilling -->
<!-- parent: map-uanalyze-cli -->

**Type:** grilling (HITL)
**Status:** ✅ closed（2026-08-23，assignee: agent）

## Resolution — A12 批次 EPS CSV：本體不進 bot，夾帶的股名表增量引入

**比對事實：** `get_eps.py` 抓 8 種資料，逐一對照後——資料面幾乎全被前面涵蓋，只有 2 個是新的：
| get_eps fetch | 端點 | 已決策狀態 |
|---|---|---|
| `fetch_quarterly_eps_tracking` | `EPSTrackingActualVSForecastModule` | A3（ua-04 引入）|
| `fetch_per_share_valuation` | `PerShareValueForValuationModel` | A4 財務指標（ua-04）|
| `fetch_stock_valuation` | `HistoricalPer/Pbr`+`PE_Band/PB_Band` | A6（ua-04 **不引入**）|
| `fetch_supply_chain_pool` | `StockComparisonStockPool` | A7（ua-04）|
| `fetch_order_visibility` | `OrderVisibility`+`ContractLiability` | A8（ua-04）|
| DCF | dcf_valuation_calculator | A5（ua-05）|
| `get_stock_pool_map` | `gidp/StockPool` | ⚠️新 → **引入（取代股名表）**|
| `fetch_broker_eps_estimates` | `gidp/EPSFilterTableE0001` | ⚠️新 → **不引入**（使用者裁決）|

### 決策

- **A12 批次 CSV 本體 = 不進 bot，保留獨立 CLI**（與 ua-05「批次 CSV 不進 bot」一致）。批次多檔 + CSV 是離線分析形態，不適合 Telegram 即時互動。要批次分析直接跑 `get_eps.py`。
- **`fetch_broker_eps_estimates`（各券商個別 EPS 明細）= 不引入**（使用者裁決；A3 共識平均已足夠）。
- **`get_stock_pool_map`（`gidp/StockPool`）= 引入，取代現有股名對照機制**：
  - 實測 `GET gidp.uanalyze.com.tw/data_fetch/api/StockPool?country=TW`（C 套 GIDP token）回 **12,361 檔** `{stock_code, stock_name, exchange_code}`（如 2330→台積電），是現有 `data/stock_names.json`（seed 20）的超集。
  - **取代做法 (a)**：啟動/首次查詢時打一次 StockPool 灌入本地表（`data/stock_names.json` 或記憶體），之後查本地；**定期刷新（如每週）**；**Agent 自成長邏輯退役**（全表已有，不需再邊查邊長）。
  - `lookup_stock_name` / `fetch_news <代號>` 介面不變，資料源從 20 檔 seed 換成 12361 全表。
  - **保留 `lookup_stock_name --set` 手動寫回當後備**（萬一 StockPool 缺某檔），成本低。

## 待實作接口（給 spec）

- `tools/uanalyze.py`（或 `lookup_stock_name.py`）：新增 `fetch_stock_pool()` 打 `gidp/StockPool` 回全表 dict，複用 `UAnalyzeAuth` gidp helper（ua-02）。
- `tools/lookup_stock_name.py`：改為從 StockPool 灌入的本地表查詢 + 定期刷新；移除 Agent 自成長主路徑，保留 `--set` 後備。
- 影響現有功能（改動而非新增）：`lookup_stock_name`、`fetch_news` 個股過濾 —— 介面不變，實作需回歸測試。

## Question

決定 A12 是否引入、及形態：

- **A12 批次 EPS CSV 匯出** — `option_batch_eps_csv` + `get_eps.py` main；多檔個股批次抓法人預估 EPS → 匯出 CSV
- `fetch_broker_eps_estimates`（各券商個別預估）、`fetch_single_stock_consensus`

**與現有的張力：**
- 「批次多檔 + CSV 匯出」是離線分析形態，與 Telegram 即時互動形態不同 → 要不要進 bot？還是保留為獨立 CLI 工具？
- 若進 bot，多檔輸入 + CSV 交付怎麼設計
- 與群3的 A3（單檔共識）共用底層 `get_eps` 函式，可能該一起考慮

**來源檔案：** `uanalyze_cli/get_eps.py`（`fetch_broker_eps_estimates` line 426、`main` line 541）、`uanalyze_cli/uanalyze_cli.py` line 932
