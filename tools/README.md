# tools/ — 工具能力清單

每個工具都是獨立的 Python script，**CLI + import 雙入口**、回傳 JSON。

**兩層架構**（Agent 驅動）：

- **`tools/raw/`（純取數層）**：一個 API 端點一個 function，只抓原始資料、回最完整結構，
  **不判讀、不跨端點組合、不計算**。CLI：`python tools/raw/<源>.py ...`。
- **`tools/analysis/`（功能層）**：`import` raw 層做組合 / 計算 / 判讀 / 繪圖。是 bot 確定性
  路徑（`/p`、推播）與 Agent 的消費對象。CLI：`python tools/analysis/<feature>.py ...`。
- **根目錄**：只剩資料工具 `lookup_stock_name`（純本地對照表，不歸兩層）。
  快捷/即時（`get_stock_price`/`draw_*`）、新聞、文件摘要都已歸 `analysis/`；各家 API 取數歸 `raw/`。

> **Agent 用法**：raw 只給原始資料。要「法人共識報告」「同業比較」這種**純並排組合**，
> Agent 自己 call 多個 raw fetcher 再整理（見下「組合分析」）；要「DCF / PE Band 百分位」
> 這種**有計算**的，用 analysis 層現成 function，別自己重算。

本檔只記錄「每個工具能取得哪些資料 / 提供哪些功能」。
**詳細用法（參數、回傳格式）一律寫在各 `.py` 檔案最上方的 docstring**，需要時直接看該檔開頭。

---

## analysis/ 快捷 / 即時 / 新聞 / 文件

| 檔案 | 能取得的資料 / 功能 |
|------|---------------------|
| [`analysis/get_stock_price.py`](analysis/get_stock_price.py) | 即時 / 收盤股價：現價、漲跌、漲跌幅、成交量（委派 `raw/fugle` 報價→`raw/finmind` tick 快照 fallback；best-effort 附基本面，走 `analysis/fundamentals.py`） |
| [`analysis/draw_kchart.py`](analysis/draw_kchart.py) | K 線圖（可指定天數，委派 `raw/fugle` 歷史日K）→ 圖片路徑 |
| [`analysis/draw_intraday_chart.py`](analysis/draw_intraday_chart.py) | 盤中分時走勢折線圖（委派 `raw/fugle` 分鐘K + 報價）→ 圖片路徑 |
| [`analysis/news.py`](analysis/news.py) | 新聞聚合（15 來源）+ 個股過濾/去重/排序；`--fulltext` 轉呼 raw 抓單篇全文。import `raw/news_sources` |
| [`analysis/summarize_document.py`](analysis/summarize_document.py) | 任意 URL / PDF 擷取 + AI 摘要（唯一呼叫 AI 的 analysis 工具） |

## raw/ 純取數層

### [`raw/uanalyze.py`](raw/uanalyze.py) — UAnalyze 各端點 raw fetcher

CLI：`python tools/raw/uanalyze.py <fetcher> <參數...>`（fetcher 名見檔頭 docstring 完整清單）。
一端點一 fetcher，回原始資料。認證固定（cronjob cookie / gidp 固定 token / jwt，端點自動選對）。

| fetcher | 能取到什麼 |
|---------|-----------|
| `historical_per` / `historical_pbr` / `pe_band` | 本益比 / 股價淨值比月序列（近20年）/ PE Band(含同業中位數 refdata) |
| `per_share_value` | 每股 FCF/EPS/ROE/ROIC… 多年 |
| `institutional_net` / `margin_balance` / `short_interest` | 三大法人買賣超 / 融資 / 融券 |
| `major_investors_holdings` / `shareholders_stats` | 外資董監持股比率 / 股東人數大戶比率 |
| `profit_margins` / `cash_flow_trend` / `cash_dividend_payout` | 三率 / 現金流 / 現金股息發放率 |
| `eps_revenue_consensus` / `revenue_tracking` / `eps_tracking` / `broker_eps_table` | 年度共識 / 月營收追蹤 / 單季EPS / 各券商EPS |
| `smart_estimate` / `eps_route` / `margin_route` / `rating_trend` | Reuters 8指標預估 / 未來五季路徑 / 評等趨勢 |
| `stock_comparison_pool` / `order_visibility` / `web_stock_info` / `transcript_detail` | 同業池 / 訂單能見度 / 即時基本面+逐字稿清單 / 逐字稿全文 |
| `report_summaries` | 研究報告摘要（帶代號=單股；不帶=全站最新） |
| `completion` / `ai_chat` | UAnalyze AI 分析 / AI 知識庫問答（呼叫外部 AI，仍屬取數） |
| `company_keywords` | 批次雷達（多類全站資料，可數十 MB） |

### 其他 raw 資料源

| 檔案 / 指令 | 能取得的資料 |
|-------------|--------------|
| [`raw/cnyes.py`](raw/cnyes.py) `--eps`/`--target`/`--quote` | 鉅亨網：FactSet 預估 EPS / 分析師目標價 / 即時報價 |
| [`raw/finmind.py`](raw/finmind.py) | FinMind：本益比/淨值比/殖利率、日收盤價量、月營收、三大財報、股利、三大法人、融資融券、外資持股、基本資料、新聞、`--snapshot` 即時 tick 快照（各一子指令；⚠️ 有額度上限） |
| [`raw/fugle.py`](raw/fugle.py) | 富果：即時報價（含五檔）、交易屬性、當日分鐘 K、成交明細、分價量、歷史日 K、52 週統計 |
| [`raw/yfinance_data.py`](raw/yfinance_data.py) | Yahoo Finance：精選基本面欄位、分析師目標價 + 評等、歷史價、年度損益表 |
| [`raw/news_sources.py`](raw/news_sources.py) | 15 個新聞來源各一 fetcher（CNYES/MoneyDJ/Yahoo/UDN/UAnalyze/Fugle/Vocus/FinGuider/Fintastic/Forecastock/NewsDigest/SinoTrade/Pocket/UAnalyze專欄/Buffett+Marks）+ 全部並行抓取 + 單篇全文（只抓不過濾） |
| [`raw/broker_reports.py`](raw/broker_reports.py) | 券商研究報告（單一來源=朋友 Google Drive）：`--stock`/`--sector` 查索引、`--detail` 抓單篇 .md 全文、`--stats` 看索引統計、`--sync` 重建索引 |

## analysis/ 功能層

| 檔案 / 指令 | 提供的功能（call raw 組合/計算） |
|-------------|--------------------------------|
| [`analysis/valuation.py`](analysis/valuation.py) `--lohas` | 樂活五線譜（股價回歸 ±3SD 七線 + 機率）← raw/fugle |
| `--pe` / `--pb` | PE / PB 河流圖（歷史四分位 + ±3SD + 百分位）← raw/finmind |
| `--eps-momentum` | EPS 動能（FactSet 上/下修趨勢）← raw/cnyes |
| `--target` | 目標價彙整（CNYES + Yahoo 並列）← raw/cnyes + raw/yfinance |
| `--dcf 2330 [--csv]` | 時間加權動態 DCF 估值（內在價值/前瞻價值/信心度）← raw/uanalyze 法人共識；`--csv` 可多檔輸出 |
| `--pe-band` | 相對估值 PE/PB Band（長歷史 + 同業本益比中位數 + 現值百分位）← raw/uanalyze |
| `--all` | lohas/pe/pb/eps-momentum/target 彙整 |
| [`analysis/fundamentals.py`](analysis/fundamentals.py) `<代號>` | 即時基本面摘要（收盤/漲跌幅/本益比/最新財報/月營收/掛牌類別）← raw/uanalyze；`/p` 用，best-effort |
| [`analysis/forecast.py`](analysis/forecast.py) `--smart-estimate`/`--forecast-route` | 法人前瞻預估整理（8指標平均/最低/最高 逐年）/ 未來五季路徑+評等趨勢 ← raw/uanalyze |
| [`analysis/reports.py`](analysis/reports.py) `[代號]` | 研究報告清單（帶代號=單股；不帶=全站最新，推播用）← raw/uanalyze |

> UAnalyze 認證：一次帳密登入後依 domain 取三種認證材料（JWT / cookie / 固定 GIDP token），
> 細節見 `raw/uanalyze.py` 檔頭。登入在 raw 層處理，analysis 層 call function 即可、不碰認證。

## 資料工具（根目錄）

| 檔案 | 能取得的資料 / 功能 |
|------|---------------------|
| [`lookup_stock_name.py`](lookup_stock_name.py) | 台股代號 ↔ 公司名對照表（讀查 / `--set` 手動後援 / `--refresh` 從 UAnalyze StockPool 全表刷新） |

---

## 組合分析：怎麼把工具串起來

單一工具給的是「一塊資料」；下面幾條是把多支工具組合起來做一件事的常見套路，
給想自己跑分析的人（或協調工具的 Agent）參考。

### 查某檔個股的新聞

台股新聞標題寫公司中文名（「台積電」）不是代號。所以先查名再查新聞：

1. `lookup_stock_name.py <代號>` → 拿到公司中文名。
2. 用公司名餵給 `analysis/news.py <公司名> --limit 10` → 拿到含該名稱的新聞。
3. 想深讀某篇 → 拿該篇 url 丟 `analysis/news.py --fulltext <URL>` 抓全文。

### 做一份完整個股分析報告

1. **AI 面向分析**：`raw/uanalyze.py completion <代號> <面向>`（單面向 AI 分析）。要多面向就多 call
   幾次（近況發展/產品線/利多/利空/資本支出…依產業與問題挑）。
2. **相對估值 / 貴不貴**：`analysis/valuation.py --pe-band <代號>`（UAnalyze 長歷史 PE/PB + 同業
   本益比中位數 + 百分位）；或 `--pe`/`--pb`/`--lohas`（FinMind 自算河流圖 / 樂活五線譜）。
3. **內在價值**：`analysis/valuation.py --dcf <代號>`（時間加權動態 DCF）。
4. **獲利品質與體質**：`raw/uanalyze.py profit_margins`（三率）、`cash_flow_trend`（現金流）、
   `per_share_value`（每股 EPS/ROE/ROIC…）。
5. **籌碼面**：`raw/uanalyze.py institutional_net`（三大法人）、`margin_balance`+`short_interest`
   （融資融券）、`major_investors_holdings`+`shareholders_stats`（持股集中度）。
6. **配息 / 存股**：`raw/uanalyze.py cash_dividend_payout`（現金股息 + 發放率）。
7. **前瞻共識（法人怎麼看未來）**：`analysis/forecast.py --smart-estimate <代號>`（法人預估
   EPS/營收/毛利率/淨利/資本支出/股息 平均・最低・最高，逐年）、`--forecast-route`（未來五季
   路徑 + 評等趨勢）。
8. **券商研究佐證**：`raw/broker_reports.py --stock <代號>`，某篇相關再 `--detail <file_id>`。

> 拿到各塊 raw 資料後，**Agent 自己彙整成報告**。像「法人共識年度表」「同業多維比較」這種純並排
> 組合**沒有現成 function**（刻意不預組）——自己 call 需要的 raw fetcher 再排版即可。

### 法人共識（Agent 自組範例）

沒有 `--consensus` 現成指令。要「法人共識全貌」自己組：
1. `raw/uanalyze.py eps_tracking <代號>`（單季 EPS 實際 vs 法人共識）
2. `raw/uanalyze.py eps_revenue_consensus <代號>`（年度 營收/EPS/本業EPS 共識）
3. `raw/uanalyze.py revenue_tracking <代號>`（月營收共識/達成率）
4. `raw/uanalyze.py broker_eps_table <代號>`（各券商逐年預估，需自行以 stock_code 過濾）

### 跟同業比較（Agent 自組）

沒有 `--peers-compare` 現成指令。自己組：
1. `raw/uanalyze.py stock_comparison_pool <代號>` 取同業/供應鏈代號清單。
2. 對本檔 + 每個同業各跑 `analysis/valuation.py --pe-band` 或 `raw/uanalyze.py profit_margins`，
   自己排成對照表。

### 產業 / 主題分析

`raw/broker_reports.py --sector <關鍵字>`（記憶體、CPO、散熱、被動元件…）查產業/總經/策略報告，
回清單 + 摘要，某篇特別相關時再 `--detail <file_id>` 抓全文。

---

## 同主題多來源時，該用哪個？

有些資料多支工具都拿得到，但**來源特性不同**（即時性、額度、資料未必一致）。下表給首選與備援：

| 主題 | 首選 | 備援 / 其他 | 說明 |
|------|------|-------------|------|
| 即時報價 | `analysis/get_stock_price.py`（Fugle→FinMind fallback，秒回） | `raw/fugle.py --quote`（要五檔）、`raw/cnyes.py --quote` | ⚠️ 別為報價單獨打 `raw/finmind.py`（**FinMind 有額度上限**，留給非即時的財報/歷史類） |
| 歷史日 K（數據） | `raw/fugle.py --candles`（即時性佳、無明顯上限） | `raw/yfinance_data.py --history` | `raw/finmind.py --price` 列末位（**省 FinMind 額度**） |
| 歷史 K（畫圖） | `analysis/draw_kchart.py`（唯一產圖） | — | 要圖用這，要數據用上面 |
| 本益比 / PE | 依用途，**三者不等價、非重複** | — | 問「貴不貴」用 `analysis/valuation.py --pe-band`（UAnalyze 相對估值+同業中位數+百分位）；要自算河流圖用 `analysis/valuation.py --pe`（FinMind 四分位+SD）；要 raw 序列用 `raw/finmind.py --per`（注意額度）或 `raw/uanalyze.py historical_per`（近20年） |
| 目標價 | `analysis/valuation.py --target`（**已並列 CNYES + Yahoo 兩家**，不合併） | `raw/cnyes.py --target`、`raw/yfinance_data.py --target` | ⚠️ **各家目標價不一定一樣**，首選刻意兩家並陳 |
| 前瞻預估 | 依角度，**各有獨到、非重複** | — | 多指標區間 `analysis/forecast.py --smart-estimate`；逐季路徑+評等 `--forecast-route`；估值模型 `analysis/valuation.py --dcf`；FactSet 年度 EPS `raw/cnyes.py --eps` / `analysis/valuation.py --eps-momentum`。法人共識年度表自己 call raw 組（見上） |
| 財報三表 | 看需求 | — | 原始表 `raw/finmind.py --income/--balance/--cashflow`（額度）；UAnalyze 整理版 `raw/uanalyze.py profit_margins/cash_flow_trend/per_share_value`；Yahoo 年度 `raw/yfinance_data.py --financials` |
| 股利 | `raw/uanalyze.py cash_dividend_payout`（現金股息+發放率） | `raw/finmind.py --dividend`（原始股利政策，額度） | 同名不同源 |
| 法人 / 融資券 | `raw/uanalyze.py institutional_net`(三大法人) / `margin_balance`+`short_interest`(信用交易) / `major_investors_holdings`(持股) | `raw/finmind.py --institution` / `--margin`（原始，額度） | — |
| 新聞 | `analysis/news.py`（15 來源聚合 + 個股過濾 + 單篇全文） | `raw/finmind.py --news`（額度） | 兩套新聞源不同 |

原則：**即時類優先用 Fugle/UAnalyze，FinMind 因有額度上限留給非即時的歷史/財報**；同主題多支不是重複，是「即時性 / 來源 / 加工程度」的取捨——依情境選，README 這張表就是依據。

---

> 詳細參數與回傳格式看各 `.py` 檔頭的 docstring；估值數學核心（線性回歸、標準差帶、四分位、
> 百分位、DCF 折現）在 `analysis/valuation.py` 內以純 numpy/math 實作。
