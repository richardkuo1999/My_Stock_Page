# ua-01 UAnalyze 認證機制調查（唯讀，事實摘要）

調查對象：`stocktool/uanalyze_cli`（三套認證） vs 現有 `My_Stock_Page/tools/uanalyze.py`（僅 JWT Bearer 一套）。
所有斷言皆引用 `檔案:行號`。路徑相對於 `/Users/richardkuo/Desktop/stock code/`。

---

## 1. 三套認證機制總覽

| # | 名稱 | Domain | Header / 傳遞方式 | 憑證來源 | 用途端點 |
|---|------|--------|------------------|----------|----------|
| A | **JWT Bearer**（App API） | `api.uanalyze.com.tw`（`APP_API_DOMAIN`） | `Authorization: Bearer <access_token>` | 帳密登入 `/auth/token` | 登入/刷新 token；`data.uanalyze.twobitto.com` 的 `completions`、`report-summaries` | 
| B | **Session cookie** | `cronjob.uanalyze.com.tw`（`DATA_API_DOMAIN`） | `requests.Session` 帶 `access_token` cookie（**非** Authorization header） | 同一組帳密登入產生的 `access_token`，寫進 cookie 檔 | `data_fetch/api/{Module}/{ticker}`（EPS 追蹤、估值、PE/PB Band、供應鏈、訂單能見度…） |
| C | **寫死 GIDP token** | `gidp.uanalyze.com.tw`（`GIDP_API_DOMAIN`） | `Authorization: Bearer tquEQGIZfck2lYDdBst9LBF5p6jfQepV`（前端 JS 寫死固定值） | 硬編碼常數，非登入產生 | `data_fetch/api/WebStockInfo`、`StockPool`、`EPSFilterTableE0001` |

Domain 常數定義：`get_eps.py:24-26`
```
APP_API_DOMAIN  = "https://api.uanalyze.com.tw"
DATA_API_DOMAIN = "https://cronjob.uanalyze.com.tw"
GIDP_API_DOMAIN = "https://gidp.uanalyze.com.tw"
```
GIDP token 常數：`get_eps.py:19-20`（註解明說「固定公開 GIDP Token (前端 JS 寫死的，用於 gidp.uanalyze.com.tw API)」）。

---

## 2. 各套認證流程（cited）

### A — JWT Bearer（帳密登入）
- 登入：`POST {APP_API_DOMAIN}/auth/token`，body `{email, password}` → 回 `data.access_token` — `get_eps.py:149-171`。
- 刷新：`POST {APP_API_DOMAIN}/auth/token/refresh` — `get_eps.py:174-190`。
- headers（Origin/Referer = `pro.uanalyze.com.tw`）— `get_eps.py:59-66`。
- `ensure_token_and_login` 產生兩個欄位存進 `uanalyze_token.json`：
  - `token` = `"Bearer {GIDP_TOKEN}"`（**注意：這是 GIDP 硬編碼 token，不是 JWT**）
  - `jwt_token` = `"Bearer {access_token}"`（真正的登入 JWT）
  - 見 `get_eps.py:230-242`（refresh 分支）與 `get_eps.py:248-257`（帳密登入分支）。

### B — Session cookie（cronjob domain）
- 登入回應的 `access_token` 被 `_save_cookies_from_login` 寫成 `access_token` cookie（domain `pro.uanalyze.com.tw`）— `get_eps.py:99-108`。
- `_get_session` 從 cookie 檔建 `requests.Session`，把 cookie 掛上去 — `get_eps.py:262-281`。
- A3–A9 端點全部用 `_get_session()` + `session.get(url)`，**不帶 Authorization header**，靠 cookie 認證：
  - EPSTracking：`get_eps.py:290-300`
  - PerShareValue：`get_eps.py:305-315`
  - HistoricalPer/Pbr/PE_Band/PB_Band：`get_eps.py:349-365`
  - StockComparisonStockPool：`get_eps.py:378-386`
  - OrderVisibility/ContractLiability：`get_eps.py:394-406`
- 全部打在 `DATA_API_DOMAIN`（`cronjob.uanalyze.com.tw`）`/data_fetch/api/{Module}/{ticker}`。

### C — 寫死 GIDP token（gidp domain）
- `uanalyze_cli.py` 的 `get_valid_token()` 回傳 `(token, jwt_token)`，`token` 即 `Bearer {GIDP_TOKEN}` — `uanalyze_cli.py:82-105`（讀 `saved["token"]`／`saved["jwt_token"]`）。
- GIDP domain 端點用 `Authorization: token`（= GIDP 硬編碼）：
  - WebStockInfo：`uanalyze_cli.py:148-155`（`Authorization: token`）；同樣端點 `dcf_valuation_calculator.py:66`。
  - StockPool / EPSFilterTableE0001：`get_eps.py:419`, `get_eps.py:430`（用傳入的 `headers`，該 `headers` 的 `Authorization` = `token` = GIDP，見 `dcf_valuation_calculator.py:394-402` 組 headers 的地方）。
- twobitto completions / report-summaries 用的是 `jwt_token`（JWT）：`uanalyze_cli.py:210-216`、`uanalyze_cli.py:333-339`。

---

## 3. 關鍵事實：cookie 的 access_token 與 JWT 是同一個 token

唯讀驗證（decode 現存快取檔）：
- `uanalyze_token.json` 的 `jwt_token`（去掉 `Bearer `）與 `uanalyze_session_cookies.json` 的 `access_token` cookie **byte-for-byte 相同**。
- JWT payload：`sub=145820`, `aud=8`, `exp=1787428690`。
- `token` 欄位 = `Bearer tquEQGIZfck2lYDdBst9LBF5p6jfQepV`（= GIDP 硬編碼，與 JWT 無關）。

依據：兩檔皆由同一次 `login_with_password` 的回應寫出 —
`jwt_token` 來自 `get_eps.py:255`（`f"Bearer {login_data['access_token']}"`），
cookie `access_token` 來自 `get_eps.py:78-88`（`_save_cookies_from_login` 寫入 `login_data["access_token"]`）。
兩者輸入同為 `login_data["access_token"]`，故必然相同（實測亦相同）。

> 結論：**B（cookie）與 A（JWT）本質是同一組帳密登入產出的同一個 access_token**，差別只在「放 cookie」vs「放 Authorization header」。

---

## 4. 現有 My_Stock_Page/tools/uanalyze.py（僅 JWT 一套）

- `AUTH_BASE_URL = os.getenv("UANALYZE_AUTH_URL", "https://api.uanalyze.com.tw")` — `tools/uanalyze.py:24`（**與 A 的 `api.uanalyze.com.tw` 相同**）。
- `BASE_URL = "https://data.uanalyze.twobitto.com"` — `tools/uanalyze.py:25`（資料端點，同 CLI 的 twobitto domain）。
- 登入 `POST {AUTH_BASE_URL}/auth/token`、刷新 `/auth/token/refresh`，取 `access_token` — `tools/uanalyze.py:44-72`、`tools/uanalyze.py:74-96`。
- 請求 header 格式：`Authorization: Bearer {token}` — `tools/uanalyze.py:120-124`；401 自動 refresh/re-login — `tools/uanalyze.py:130-142`。
- 目前只打兩個端點：`/completions`（`tools/uanalyze.py:161`）、`/api/report-summaries`（`tools/uanalyze.py:180`, `tools/uanalyze.py:206`）。

> 現有工具用的 JWT domain（auth=`api.uanalyze.com.tw`、data=`data.uanalyze.twobitto.com`）與 CLI 的 A 套 **完全一致**。

---

## 5. 能否統一成一套 JWT Bearer？（結論與依據）

### 可統一的部分
- **A（JWT）**：現有工具已經在用，無需改動。
- **B（cookie，cronjob domain）**：cookie 的 `access_token` = JWT access_token（見第 3 節實測）。理論上把同一個 token 改成 `Authorization: Bearer <access_token>` header 打 `cronjob.uanalyze.com.tw` **有機會**成立，因為 token 身分相同。
  - **未驗證項（重要）**：本次為唯讀調查，**未實際發送 HTTP 請求**驗證 `cronjob.uanalyze.com.tw` 是否接受 Bearer header（而非只吃 cookie）。CLI 現況一律用 cookie（`get_eps.py:290-406`），無反證顯示它接受 header。此為統一成 JWT 的**唯一實測缺口**，需一次 online 驗證（打一個 module 端點比較 cookie vs Bearer 的回應）。

### 難以統一的部分
- **C（GIDP 寫死 token，gidp domain）**：`gidp.uanalyze.com.tw` 端點（WebStockInfo / StockPool / EPSFilterTableE0001）用的是**固定公開常數** `tquEQGIZfck2lYDdBst9LBF5p6jfQepV`，**不是** JWT，也不是登入產生（`get_eps.py:19-20`；用法 `uanalyze_cli.py:148-155`、`dcf_valuation_calculator.py:66`）。
  - 這是另一個 domain 的另一套 API-key 式認證。是否接受 JWT Bearer **未知且未驗證**；就 CLI 現況它只吃 GIDP token。
  - 若要統一成 JWT，必須先驗證 `gidp.uanalyze.com.tw` 是否接受登入 JWT；否則 GIDP 端點無法併入 JWT 一套。

### 哪些端點目前「只能用 cookie / 只能用 GIDP」（就現有程式碼事實）
- 只用 cookie（`cronjob.uanalyze.com.tw`）：EPSTracking、PerShareValue、HistoricalPer/Pbr、PE_Band、PB_Band、StockComparisonStockPool、OrderVisibility、ContractLiability（`get_eps.py:290-406`）。
- 只用 GIDP 硬編碼 token（`gidp.uanalyze.com.tw`）：WebStockInfo、StockPool、EPSFilterTableE0001（`uanalyze_cli.py:155`、`get_eps.py:419`、`get_eps.py:430`）。
- 已用 JWT（`data.uanalyze.twobitto.com`）：completions、report-summaries（`uanalyze_cli.py:210-216`、`tools/uanalyze.py:161-180`）。

---

## 6. 一句話結論

三套裡 **A（JWT）與 B（cookie）實際上是同一個 access_token 的兩種攜帶方式**（實測 byte 相同），最有可能統一成 JWT Bearer；但 **C（GIDP `gidp.uanalyze.com.tw` 寫死 token）是不同 domain 的固定 API-key**，能否改吃 JWT 未知。要落地統一，缺一次 online 唯讀驗證：分別對 `cronjob` 與 `gidp` 端點用 Bearer header 打一次，確認是否 200。此調查為唯讀，未做該線上驗證，未改任何現有檔案。

---

## 附錄：online 唯讀驗證結果（ua-08，2026-08-22）

實測（用現有 `tools/uanalyze.py` 登入拿 JWT，對真實 API 發唯讀 GET）：

| 測試 | domain / 端點 | 認證方式 | 結果 | 判讀 |
|---|---|---|---|---|
| 1 | `cronjob` `/data_fetch/api/EPSTrackingActualVSForecastModule/2330` | `Authorization: Bearer <JWT>` | **403 Forbidden**（nginx/1.10.3） | cronjob **不吃** Bearer header |
| 2 | `cronjob` 同上 | JWT 塞進 `access_token` cookie（單一 cookie） | **403 Forbidden** | 單一 cookie 不夠 |
| 3 | `gidp` `/data_fetch/api/WebStockInfo/2330` | `Authorization: Bearer <JWT>` | **401** `{"detail":"Invalid or missing token"}` | gidp **不吃** JWT |
| 4 | `gidp` 同上 | `Authorization: Bearer <寫死 GIDP token>` | **422**（缺 `country` query 參數） | gidp **只認**寫死 GIDP token；422=認證過、只差參數 |

**cookie 檔實際內容**（`uanalyze_cli/uanalyze_session_cookies.json`）：4 個 cookie — `access_token`(1078B)、`refresh_token`、`token_type`、`expires_in`，domain 全是 `pro.uanalyze.com.tw`。測試 2 只塞 `access_token` 且 domain 不符 → 403。

### 結論（推翻「全統一成 JWT」的樂觀假設）

- **B（cronjob）不能改用 Bearer header**。就算 token 與 JWT 相同，cronjob 端要的是**完整 4-cookie 的 session**（domain `pro.uanalyze.com.tw`），不是 header。→ B 得沿用「登入後把整組 cookie 存起來、用 `requests.Session` 帶 cookie」的方式（即移植 `get_eps.py` 的 `_save_cookies_from_login` + `_get_session`）。
- **C（gidp）不能用 JWT**，只認寫死的公開 GIDP token（`tquEQ...`）。→ C 直接沿用寫死 token 即可（它是前端公開常數）。
- **A（twobitto completions/report-summaries）**：現有 `tools/uanalyze.py` 已用 JWT，無需改。

→ 三套認證**無法收斂成一套**。實際落地是「一次帳密登入 → 拿到 access_token → 同時 (a) 當 JWT Bearer 打 twobitto、(b) 存成完整 cookie session 打 cronjob」＋「C 用寫死 GIDP token 打 gidp」。好消息：**只需登入一次**（A/B 同源 token），認證整合的成本主要在「多存一份 cookie session + 保留一個 GIDP 常數」。

---

## 附錄二：完整 4-cookie 驗證（ua-02 決策 2，2026-08-22）

補打唯讀驗證，釐清 403 真因：

| 測試 | cronjob `/data_fetch/api/EPSTrackingActualVSForecastModule/2330` | 結果 |
|---|---|---|
| A | 完整 4-cookie（access_token/refresh_token/token_type/expires_in），**不帶** Origin/Referer | **403 Forbidden** |
| B | 完整 4-cookie **+** `Origin: pro.uanalyze.com.tw` `Referer: https://pro.uanalyze.com.tw/` | **200 OK**（回真實 data）|

**真因：** cronjob 的 nginx 除了要 cookie session，**還檢查 Origin/Referer**。先前 403 是缺 Origin/Referer（現有 `tools/uanalyze.py` 的 JWT 請求本來就帶 Referer 但沒帶 Origin，且 cronjob 要 cookie 不吃 Bearer）。

**關鍵簡化：** login 回應 (`POST api.uanalyze.com.tw/auth/token`) **一次就回全部 4 個欄位**（實測 payload keys 含 `token_type, expires_in, access_token, refresh_token`）。→ 打 cronjob 只需把 login 回應的這 4 欄在**記憶體**組成 cookie + 帶 Origin/Referer，**不需移植 CLI 的 cookie 檔落地機制**。

### 三套認證最終落地（實證）
- **A** `data.uanalyze.twobitto.com`：`Authorization: Bearer <access_token>`（現有，不動）
- **B** `cronjob.uanalyze.com.tw`：4-cookie session（同一次 login 的回應）+ `Origin/Referer: pro.uanalyze.com.tw`
- **C** `gidp.uanalyze.com.tw`：`Authorization: Bearer <寫死 GIDP 常數>` + 需要 `country` 等 query 參數
- 全部**共用一次 login**（A/B 同 token；C 是獨立公開常數）
