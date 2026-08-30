# UAnalyze 認證統一策略決策

<!-- labels: wayfinder:grilling -->
<!-- parent: map-uanalyze-cli -->
<!-- blocked-by: ua-08-online-auth-verify -->
<!-- blocks: ua-03-jwt-completions, ua-04-datafetch-modules -->

**Type:** grilling (HITL)
**Status:** ✅ closed（2026-08-22，assignee: agent）

## Resolution — UAnalyze 認證統一策略

基於 ua-01 + ua-08 + 補驗證的事實（三套認證無法合一、但共用一次 login；4-cookie+Origin/Referer 實測 200）：

- **決策 1（落地形態）= 單一擴充 `UAnalyzeAuth` 類**。在現有 `tools/uanalyze.py` 的 `UAnalyzeAuth` 上擴充，一次登入、對外三個 request helper：
  - `_request_jwt`（現有 `_request_with_auth`）→ `data.uanalyze.twobitto.com`，`Authorization: Bearer`
  - `_request_cookie`（新增）→ `cronjob.uanalyze.com.tw`，4-cookie session + `Origin/Referer: pro.uanalyze.com.tw`
  - `_request_gidp`（新增）→ `gidp.uanalyze.com.tw`，`Authorization: Bearer <GIDP 常數>` + `country=TW` 等 query
- **決策 2（cookie 怎麼存）= 記憶體組 4-cookie**。login 回應一次回全部 4 欄（access_token/refresh_token/token_type/expires_in），打 cronjob 時在記憶體組成 cookie 即可。**不移植 CLI 的 cookie 檔落地機制**。
- **決策 3（GIDP 常數放哪）= 模組常數**。`GIDP_TOKEN = "tquEQ..."` 寫進 `tools/uanalyze.py`，加註解「UAnalyze 前端公開常數（非機密），失效需從前端 JS 更新」。理由：前端公開值非機密（不進 .env）、A3/A5/A9 共用（一處定義符合 locality）。
- **決策 4（範圍）= 只定認證策略**，各功能是否引入留 ua-04/ua-03/ua-05。

**成本評估：** 只需登入一次；新增一個 cookie helper + 一個 gidp helper + 一個常數。認證整合不重。

**resolve 時發現（回頭更新地圖）：** GIDP domain 不只 WebStockInfo——A3 法人共識同時用 cronjob(B, 單季EPS) 與 gidp(C, 月營收/年營收EPS共識)，A5 DCF 三套全用。→ ua-04 body 已修正標明 A3 跨 B+C。

## Question

基於認證調查（ua-01）的事實，決定 UAnalyze 認證在現有 `tools/uanalyze.py` 的統一策略：

- 三套認證（JWT / session cookie / GIDP token）要收斂成幾套？
- 現有 `tools/uanalyze.py` 的 `_request_with_auth`（JWT）要不要擴充成也能打 `data_fetch/api/{Module}` 端點？
- cookie 檔（`uanalyze_session_cookies.json`）要不要沿用，還是全改 JWT？
- GIDP 全台股名對照要不要接進來（與現有 `data/stock_names.json` 的關係，見 map「Not yet specified」）？

**這是所有 data_fetch 類功能（A3–A9）與 completions 類（A1/A2）引入的前置決策。** 決定後才能談各功能形態。

**產出：** 認證統一策略的決策（記錄到 map Decisions so far）。
