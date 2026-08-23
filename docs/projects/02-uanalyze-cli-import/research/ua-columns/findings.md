# UAnalyze 專欄／文章庫 API — Findings

調查日期：2026-08-23
調查方式：真實憑證登入（.env）+ 唯讀 GET 實測 + 反查 pro.uanalyze.com.tw 前端 bundle。
（過程腳本：`research/ua-columns/probe*.py`，皆為唯讀，不寫入 UAnalyze。）

---

## ⚠️ 更正（2026-08-23，使用者提供 Network 實際 URL 後）

**下方原始 TL;DR 的「端點已死」結論是錯的。** 錯因：本調查打的是 `data_fetch/column/search`（**底線** `data_fetch`），而正確路徑是 `data/fetch/column/search`（**斜線** `data/fetch`）。一字之差（底線 vs 斜線）導致全部落到 gateway 的「路由不存在」統一錯誤。

**正確且實測可用（200 有資料）：**
```
GET https://api.uanalyze.com.tw/data/fetch/column/search?Keywords=&page=1&per_page=N
Header: Authorization: Bearer <access_token>, Origin/Referer: https://pro.uanalyze.com.tw
```
- 回 `data.columns[]` + `data.meta{current_page, per_page, total=2369, last_page=474, has_next}`（分頁完整）
- item 欄位：`id / title / tag(如 DailyIssue) / content(全文 HTML) / create_id / top / created_at / image`
- **列表就直接帶 `content` 全文**；帶 `&id=<n>` 回單篇（`data.content` 全文 HTML）
- 內容為**跨產業專欄長文**（每日議題），與 `report-summaries`（個股研報摘要）**不同批**，不重疊。
- 真實範例 id=2453：「【AI資料中心新瓶頸】離網供電投入運轉後，設備故障風險開始浮現」。

**結論更新：A11 專欄端點存活、可用、有全文。** 下方原始 TL;DR 保留作為「底線路徑無效」的紀錄，但引入決策以本更正為準。

---

## TL;DR（核心結論）

1. **來源專案參考的 `data_fetch/column/search` 端點在目前的 UAnalyze API 上已不存在。**
   任何打到 `https://api.uanalyze.com.tw/data_fetch/...`（含 `column/search`、`columns/search`、
   加不加 Bearer、Keywords/keyword、page/per_page vs limit/offset、加不加 Origin）**一律**回
   `HTTP 200` 但 body 是 `{"error":{"message":["Not found."],"code":"E400004"}, "uri": "...", "status":"error"}`。
   這是該 gateway 的「路由不存在」統一錯誤格式，不是參數錯誤。GIDP 網域（`gidp.uanalyze.com.tw`）
   則直接回 `404 {"detail":"Not Found"}`。前端 bundle 全站也**沒有任何** `column/search` / `/column`
   路由字串 → 判定該端點已被下線或改名。
   **（↑ 此點已被上方更正推翻：真相是 `data_fetch`→`data/fetch` 斜線筆誤，端點仍存活。）**

2. **目前線上真正在用、可回傳「文章列表（標題＋日期＋摘要＋個股）」的端點是 `report-summaries`。**
   本 repo 的 `tools/uanalyze.py`（`list_latest_reports`）已經在用這條，只是 base URL 走
   `data.uanalyze.twobitto.com`。實測可正常回傳，**總數 4279 篇**（欄位 `total`）。

3. **可以只取列表併入新聞聚合。** `report-summaries` 每個 item 直接內含
   標題（`question_type`）、日期（`content_date`）、摘要（`summary`，已是完整重點文字）、
   個股代號/名稱（`name` / `stock_name`）。**不需要再抓全文**即可展示。
   唯一缺點：**沒有可直接導回網站的公開文章 URL**（無 slug / permalink 欄位，見下）。

---

## 1. 正確的 request 簽名（實測可用）

### 認證（沿用既有邏輯，無變化）
```
POST https://api.uanalyze.com.tw/auth/token
Content-Type: application/json
Body: {"email": "<UANALYZE_EMAIL>", "password": "<UANALYZE_PASSWORD>"}
Headers: User-Agent, Accept: application/json,
         Origin: https://pro.uanalyze.com.tw, Referer: https://pro.uanalyze.com.tw/
→ 200, data.access_token（JWT，長度約 1078）
```

### 文章列表（report-summaries）— ✅ 實測成功
```
GET https://data.uanalyze.twobitto.com/api/report-summaries
Query params:
    limit    : 1–200（上限 200，超過會被 clamp）
    offset   : 0-based 起始位移
    （選用）stock=<代號>、company=<名稱>、date、start_date、end_date、
             sort_by=<欄位>、sort_dir=asc|desc   ← 取自前端 query builder
Headers:
    Authorization: Bearer <access_token>   ← 一定要加 Bearer 前綴
    User-Agent, Accept: application/json,
    Origin: https://pro.uanalyze.com.tw, Referer: https://pro.uanalyze.com.tw/
```

Base URL 對照（前端 bundle 反查所得）：
| 別名 | 網域 | 用途 |
|------|------|------|
| APP_API_DOMAIN | `https://api.uanalyze.com.tw` | 登入/auth，**不**服務 report-summaries |
| APP_AI_HOST | `https://data.uanalyze.com.tw` | AI chat / completions |
| DATA_API_DOMAIN | `https://cronjob.uanalyze.com.tw` | 前端 axios 設定的資料 host（但 `/api/report-summaries` 回 404）|
| （實測可用） | `https://data.uanalyze.twobitto.com` | ✅ report-summaries 真正可回資料的 host（repo 現用值）|
| GIDP_API_DOMAIN | `https://gidp.uanalyze.com.tw` | 個股圖表資料，token = 前端寫死的 `GIDP_TOKEN` |

> 實測三個 host 打 `/api/report-summaries?limit=2`：
> `data.uanalyze.twobitto.com` → **200 有資料**；`cronjob.uanalyze.com.tw` → 404；
> `api.uanalyze.com.tw` → E400004 Not found。所以要用 `data.uanalyze.twobitto.com`。

---

## 2. 回傳 JSON 完整結構

```jsonc
{
  "status": "success",
  "data": {
    "data":   [ { …item… }, … ],   // 文章陣列
    "total":  4279,                // 全站文章總數
    "offset": 0,                   // 當前 offset（回顯）
    "limit":  3                    // 當前 limit（回顯）
  }
}
```

**沒有 `has_next` 欄位** → 翻頁靠 `offset + limit < total` 自行判斷（見第 4 節）。
（注意雙層 `data.data`，與 repo 現有 `list_latest_reports` 的解包邏輯一致。）

### item 欄位（實測列出全部 key）
`['id', 'generated_content_id', 'name', 'question_type', 'content_date', 'summary', 'valid', 'updated_at', 'stock_name', 'data']`

| 欄位 | 意義 | 範例 | 併入聚合可用性 |
|------|------|------|----------------|
| `id` | 報告 id（唯一，遞減，可去重） | `22443` | ✅ 去重鍵 |
| `generated_content_id` | 生成內容 id | `1512425` | 可能可組 URL（見下，未證實）|
| `name` | **股票代號** | `"2812"` | ✅ |
| `stock_name` | **公司名** | `"台中銀"` | ✅ |
| `question_type` | **報告主題＝當標題用**（無獨立 title 欄位）| `"近況發展"` | ✅ 標題 |
| `content_date` | **發布日期** | `"2026-08-23 00:00:00"` | ✅ 日期（取前 10 碼）|
| `summary` | **完整摘要文字**（含換行，已是重點整理）| `"台中銀獲利創高，財管手續費大增…"` | ✅ 摘要（免抓全文）|
| `updated_at` | 更新時間 | `"2026-08-23 03:40:32"` | 選用 |
| `valid` | 是否有效 | `true` | 過濾用 |
| `data` | 個股近期漲跌幅物件（非文章內容） | `{"DailyPriceChange_Percent_1D":"-", …}` | 通常不需要 |

**沒有的欄位（重點）**：
- ❌ 沒有獨立 `title`（用 `question_type` 當標題，但它偏「主題分類」而非文章標題）。
- ❌ **沒有可直接點回網站的公開文章 URL / slug / permalink**。
  只有 `id` / `generated_content_id`；前端是在自家 SPA 內用這些 id 開內頁，
  沒有對外可分享的固定連結欄位。若要導流，只能自行猜測組 pro.uanalyze.com.tw 的內頁路由（未證實可用）。
- ❌ 沒有作者欄位。
- ❌ 沒有全文欄位（本端點就是列表/摘要，全文需另打 completions/questions 類端點）。

### 一個真實 item 範例（token/密碼皆未出現）
```json
{
  "id": 22443,
  "generated_content_id": 1512425,
  "name": "2812",
  "question_type": "近況發展",
  "content_date": "2026-08-23 00:00:00",
  "summary": "台中銀獲利創高，財管手續費大增、外幣放款領先，營運結構優化。\n台中銀上半年總資產突破兆元，稅後淨利創新高，ROA、ROE升至1.06%、11.22%，受惠財富管理手續費年增53%及金融交易收益大增1.56倍，外幣放款成長8.99%帶動外幣活存提升，NIM擴至1.44%，資產品質續佳，但中小企業放款年減1.74%，顯示策略轉向大型企業客戶。",
  "valid": true,
  "updated_at": "2026-08-23 03:40:32",
  "stock_name": "台中銀",
  "data": { "DailyPriceChange_Percent_1D": "-", "DailyPriceChange_Percent_1M": "-7.82", "…": "…" }
}
```
第二筆確認：`id=22442 / question_type=近況發展 / content_date=2026-08-23 / name=6206 / stock_name=飛捷`。

---

## 3. 能否只取列表（不抓全文）？

**可以，且足夠展示。** 列表 item 本身就帶：
- 標題 ← `question_type`（＋可用 `stock_name`(`name`) 補成「台中銀(2812) 近況發展」更清楚）
- 日期 ← `content_date[:10]`
- 摘要 ← `summary`（已是 2–3 句完整重點，長度足以當新聞卡片內文）
- 去重鍵 ← `id`

**唯一限制**：沒有公開文章連結欄位，無法像其他新聞來源那樣附「原文網址」。
若聚合器欄位要求 `url`，只能留空或指向 `https://pro.uanalyze.com.tw`（首頁）。

---

## 4. 總數與分頁行為（實測）

- **總數 `total = 4279`**（比來源專案說的 2323+ 更多；資料庫持續成長中）。
- 排序：預設 `id` 遞減（＝最新在前），`content_date` 亦同步遞減。
  可傳 `sort_by=content_date&sort_dir=desc`（實測 200 OK，結果與預設一致）。
- **無 `has_next` 欄位**，翻頁規則：
  ```
  還有下一頁  ⇔  offset + limit < total
  下一頁      →  offset += limit
  ```
- **每頁上限 `limit=200`**（實測 `limit=200` 回 200 筆；前端 query builder 也把 limit clamp 在 1–200）。
- 深分頁實測（每次 limit=2）：
  | offset | 回傳筆數 | 首筆 id | 首筆 content_date |
  |-------:|--------:|--------:|-------------------|
  | 1000 | 2 | 21443 | 2026-08-14 |
  | 2000 | 2 | 20443 | 2026-08-09 |
  | 2300 | 2 | 20143 | 2026-08-07 |
  | 2400 | 2 | 20043 | 2026-08-06 |
  | 3000 | 2 | 19443 | 2026-08-01 |

  → offset 可一路往後翻到接近 4279，`id` 線性遞減，分頁穩定。

---

## 5. 結論：可否只用列表併入新聞聚合？

**可以，直接沿用。** 且 repo 內 `tools/uanalyze.py` 的 `list_latest_reports()` 已經在打這條
端點、解 `data.data`、抓 `id/name/stock_name/question_type/content_date/summary`，
和本次實測完全吻合 → **不需要新端點，也不需要 `column/search`**。

若要把「UAnalyze 專欄」當成新聞來源併入聚合，建議：
- **標題**：`f"{stock_name}({name}) {question_type}"`
- **日期**：`content_date[:10]`
- **摘要**：`summary`
- **去重**：`id`（既有 `pushed_uanalyze.json` 機制即用 id）
- **連結**：無公開 URL，欄位留空或填 `https://pro.uanalyze.com.tw`（需登入才看得到內頁）
- **來源限制備註**：內容為付費訂閱，摘要可展示，但無法提供對外原文連結。

> ⚠️ 對來源專案（`stocktool/uanalyze_cli`）的 `data_fetch/column/search` 別再投入：
> 該路由在現行 API 已失效，任何參數組合都回 E400004。線上等價功能已由
> `report-summaries` 取代。

---

## 附：本次實測所用（唯讀）腳本
- `research/ua-columns/probe.py` — column/search 參數矩陣（全數 E400004）
- `research/ua-columns/probe2.py` — 加 cookie / 替代路徑 / GIDP domain（全數 not found）
- `research/ua-columns/probe3.py` — GIDP/cronjob 路徑探測 + 前端 bundle 列舉
- `research/ua-columns/probe_reports.py` — 三個 host 打 report-summaries（確認 twobitto host 可用）
- `research/ua-columns/probe_schema.py` — 完整欄位/total/分頁實測
