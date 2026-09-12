# tools/ — 工具能力清單

每個工具都是獨立的 Python script，**CLI + import 雙入口**、回傳 JSON、**本身不呼叫 AI**
（由 Agent 協調 `chat_bot → AI → tool → AI → tool`）。

本檔只記錄「每個工具能取得哪些資料 / 提供哪些功能」。
**詳細用法（參數、回傳格式）一律寫在各 `.py` 檔案最上方的 docstring**，需要時直接看該檔開頭。

---

## 快捷 / 即時

| 檔案 | 能取得的資料 / 功能 |
|------|---------------------|
| [`get_stock_price.py`](get_stock_price.py) | 即時 / 收盤股價：現價、漲跌、漲跌幅、成交量（best-effort 附 UAnalyze 基本面） |
| [`draw_kchart.py`](draw_kchart.py) | K 線圖（可指定天數）→ 產生圖片檔，回圖片路徑 |
| [`draw_intraday_chart.py`](draw_intraday_chart.py) | 盤中分時走勢折線圖 → 產生圖片檔，回圖片路徑 |

## 新聞 / 文件

| 檔案 | 能取得的資料 / 功能 |
|------|---------------------|
| [`fetch_news.py`](fetch_news.py) | 15 來源最新新聞列表（全部或指定個股，本地關鍵字過濾）；單篇新聞全文抓取（on-demand，付費牆/動態頁回 error） |
| [`summarize_document.py`](summarize_document.py) | 任意 URL / PDF 文件內容擷取（供 Agent 摘要） |
| [`broker_reports.py`](broker_reports.py) | 券商研究報告查詢（個股報告、產業/總經/策略報告、電子時報）；輕量本地索引 + 單篇 .md 全文即時抓 Google Drive |

## UAnalyze（優分析）

| 檔案 / 指令 | 能取得的資料 / 功能 |
|-------------|---------------------|
| [`uanalyze.py`](uanalyze.py) `SYMBOL` / `--multi` | UAnalyze AI 估值分析（單一或多面向並行）；面向見檔內 `UA_PROMPTS` |
| `--reports` | 全站最新研究報告清單（監控用） |
| `--fundamentals` | 即時基本面摘要：收盤價、當日漲跌幅、本益比、最新財報、月營收、掛牌類別 |
| `--consensus` | 法人共識：單季 EPS 實際 vs 預估、月營收共識、年度共識、各法人 EPS 明細 |
| `--pershare` | 近年每股財務指標：FCF、EPS、EBITDA、ROE、ROIC… |
| `--supply` | 同業 / 供應鏈對照標的代號清單 |
| `--order` | 訂單能見度 + 合約負債（市場排行表取該股列，欄位中文化） |
| `--dcf` | 時間加權動態 DCF 估值：內在價值、前瞻價值、信心度（純計算，非 AI） |
| `--valuation` | 相對估值 PE / PB Band：長歷史序列、10 年均 ±SD 帶、同業本益比中位數、現值歷史百分位 |
| `--chips` | 三大法人買賣超：外資 / 投信 / 自營商 / 合計（近 20 日明細，單位張） |
| `--margins` | 三率趨勢：毛利率、營業利益率、稅後淨利率（近 8 季） |
| `--cashflow` | 現金流趨勢：營業 / 投資 / 籌資 / 自由現金流（近 8 季） |
| `--dividend` | 股利政策：現金股息、發放率（近 10 年） |
| `--peers-compare` | 同業多維比較：本檔 + 同業的 PE / PB / 三率對照表 |
| `--margin` | 信用交易：融資餘額 / 使用率、融券餘額 / 使用率（近 10 日） |
| `--holders` | 籌碼結構：外資 / 董監持股比率、股東人數、400 張・1000 張大戶持股比率（近 6 期） |
| `--transcript` | 法說會逐字稿：歷次清單，或指定某場的全文 |
| `--smart-estimate` | 前瞻共識：Reuters（Refinitiv）法人預估 EPS/營收/毛利率/EBIT/EBITDA/淨利/資本支出/股息（各含平均/最低/最高值，逐年含未來預估年） |
| `--forecast-route` | 前瞻共識：未來五季 營收/EPS/毛利率/營益率**預估路徑** + 分析師樂觀/中立/悲觀**評等佔比趨勢** |
| `--ask` | AI 知識庫問答：對某股問自然語言問題，可選知識庫（general 一般 / knowledge 個股深度 / teacher 投資教學），串流收集成完整答案 |
| `--radar` | 批次雷達：依關鍵字一次抓多類全站資料（company_info/ai_chat/transcript…）。**回傳可達數十 MB**，故落地成 JSON 檔、只回檔案路徑 + 每類筆數摘要（非即時問答用，適合離線大批撈取） |
| [`dcf_to_csv.py`](dcf_to_csv.py) | 把 DCF 估值結果輸出成 CSV（單檔或多檔並行；失敗檔只填代號 + error 欄） |

> UAnalyze 認證：一次帳密登入後，依 domain 取三種認證材料（JWT / cookie / 固定 GIDP token），細節見 `uanalyze.py` 檔頭。

## 原始資料源（raw-data，各家 API 各做成獨立 function）

供 Agent 按需呼叫、也可被 `valuation.py` import。

| 檔案 / 指令 | 能取得的資料 |
|-------------|--------------|
| [`cnyes.py`](cnyes.py) `--eps` | 鉅亨網：FactSet 各年度預估 EPS |
| `--target` | 分析師目標價共識 |
| `--quote` | 即時報價（數字代碼欄位已解碼） |
| `--candles` | 歷史日 K 線 |
| [`finmind.py`](finmind.py) | FinMind：本益比/淨值比/殖利率、日收盤價量、月營收、綜合損益表、資產負債表、現金流量表、股利政策、三大法人買賣超、融資融券、外資持股、基本資料、相關新聞（各一子指令） |
| [`fugle.py`](fugle.py) | 富果：即時報價（含五檔）、交易屬性、當日分鐘 K、當日成交明細、當日分價量、歷史日 K、52 週高低/成交統計（各一子指令） |
| [`yfinance_data.py`](yfinance_data.py) | Yahoo Finance：精選基本面欄位、分析師目標價 + 評等、歷史價、年度損益表（各一子指令） |

## 估值計算（不打 API，import 上面 raw-data 工具算）

| 檔案 / 指令 | 提供的估值 |
|-------------|-----------|
| [`valuation.py`](valuation.py) `--lohas` | 樂活五線譜（股價線性回歸 ±3SD 七線 + 回歸機率）← Fugle 歷史 K |
| `--pe` / `--pb` | PE / PB 河流圖（歷史四分位 + ±3SD 帶 + 現值百分位）← FinMind |
| `--eps-momentum` | EPS 動能（FactSet 跨年度預估上/下修趨勢）← CNYES |
| `--target` | 目標價彙整（CNYES 分析師共識 + Yahoo 目標均價）← CNYES + yfinance |
| `--all` | 以上全部彙整 |

## 資料工具

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
2. 用公司名餵給 `fetch_news.py <公司名> --limit 10` → 拿到含該名稱的新聞。
3. 想深讀某篇 → 拿該篇 url 丟 `fetch_news.py --fulltext <URL>` 抓全文。

### 做一份完整個股分析報告

1. **AI 面向分析**：`uanalyze.py --multi <代號> --prompts 近況發展,產品線分析,利多因素,利空因素,資本支出`
   一次並行跑多個面向（面向清單見 `uanalyze.py` 檔頭的 `UA_PROMPTS`；依產業特性與問題挑選，
   不必每檔都套同一組）。比逐一 `--prompt` 快很多。
2. **相對估值 / 貴不貴**：`uanalyze.py --valuation <代號>`（長歷史 PE/PB + 同業本益比中位數
   + 現值歷史位階）；或 `valuation.py --pe/--pb/--lohas`（自算河流圖 / 樂活五線譜）。
3. **獲利品質與體質**：`uanalyze.py --margins`（三率趨勢）、`--cashflow`（現金流/FCF）、
   `--pershare`（每股 EPS/ROE/ROIC…）。
4. **籌碼面**：`uanalyze.py --chips`（三大法人近日買賣超）、`--margin`（融資融券/軋空）、
   `--holders`（外資/董監/大戶持股集中度）。
5. **配息 / 存股**：`uanalyze.py --dividend`（現金股息 + 發放率）。
6. **前瞻共識（法人怎麼看未來）**：`uanalyze.py --smart-estimate`（法人預估 EPS/營收/毛利率
   /淨利/資本支出/股息的平均・最低・最高值，逐年）、`--forecast-route`（未來五季預估路徑 +
   分析師評等佔比趨勢）。問「未來展望/法人估多少/評等變化」時用這兩支。
7. **券商研究佐證**：`broker_reports.py --stock <代號>` 看有沒有相關報告，某篇相關再
   `--detail <file_id>` 抓全文。

### 跟同業比較

- 想「一次」拿本檔 + 同業的 PE/PB/三率對照表：`uanalyze.py --peers-compare <代號>`
  （內部自動取同業清單並逐檔組表）。
- 想自己控制比較維度：先 `uanalyze.py --supply <代號>` 取同業/供應鏈標的，再對那些標的
  各自取數據（`valuation.py` / `finmind.py` / `cnyes.py`）做對照。

### 產業 / 主題分析

`broker_reports.py --sector <關鍵字>`（記憶體、CPO、散熱、被動元件…）查產業/總經/策略報告，
回清單 + 摘要，某篇特別相關時再 `--detail <file_id>` 抓全文。

---

> 詳細參數與回傳格式看各 `.py` 檔頭的 docstring；估值方式的數學核心（線性回歸、標準差帶、四分位、百分位）在 `valuation.py` 內以純 numpy 實作。
