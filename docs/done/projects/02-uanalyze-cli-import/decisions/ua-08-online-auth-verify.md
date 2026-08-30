# online 驗證 cronjob/gidp 是否接受 JWT Bearer

<!-- labels: wayfinder:task -->
<!-- parent: map-uanalyze-cli -->
<!-- blocked-by: ua-01-auth-research -->
<!-- blocks: ua-02-auth-decision -->

**Type:** task (AFK — 1 次唯讀線上請求)
**Status:** ✅ closed（2026-08-22，assignee: agent）

## Resolution

實測 4 個唯讀 GET（詳見 `research/ua-auth/findings.md` 附錄）：

| domain | JWT Bearer | 結論 |
|---|---|---|
| cronjob（B，data_fetch 模組） | **403** | 不吃 Bearer；需完整 4-cookie session（access_token/refresh_token/token_type/expires_in，domain `pro.uanalyze.com.tw`）|
| gidp（C，WebStockInfo） | **401** | 不吃 JWT；只認寫死 GIDP token（用該 token 打回 **422 缺參數**=認證過）|
| twobitto（A，現有）| ✅ 已用 | 無需改 |

**三套認證無法收斂成一套。** 但只需**登入一次**（A/B 同源 token）：拿到 access_token 後 (a) 當 Bearer 打 twobitto、(b) 存成完整 cookie session 打 cronjob；C 沿用寫死 GIDP 常數。整合成本 = 多存一份 cookie session + 保留一個 GIDP 常數。

## Question

認證調查（ua-01）確認 A(JWT) 與 B(cookie) 是同一個 access_token，唯一缺口是：`cronjob.uanalyze.com.tw`（B 的 data_fetch 端點）和 `gidp.uanalyze.com.tw`（C 的端點）**是否接受 `Authorization: Bearer <JWT>` header**，而非只吃 cookie / 只吃寫死 GIDP token。

這是純事實驗證（不是決策），但要打真實 API，所以是 task 不是 research。做法：

1. 用現有 `tools/uanalyze.py` 的 JWT 登入拿到 access_token。
2. 對一個 `cronjob.uanalyze.com.tw/data_fetch/api/{Module}/{ticker}` 端點（如 `EPSTrackingActualVSForecastModule/2330`）發**唯讀 GET**，帶 `Authorization: Bearer <JWT>`（不帶 cookie），看是否 200。
3. 對一個 `gidp.uanalyze.com.tw` 端點（如 `WebStockInfo`）同樣用 JWT Bearer 試，看是否 200；並確認寫死 GIDP token 是否仍必要。

**產出：** 記錄兩個 domain 各自「接受 JWT Bearer 嗎」的實測結果（status code），寫進 `research/ua-auth/findings.md` 附錄。**只做唯讀驗證，不寫實作、不做統一決策**（決策留 ua-02）。

**⚠️ 需真實 UAnalyze 憑證**（`UANALYZE_EMAIL/PASSWORD`）。若環境無憑證則此 ticket 需 HITL（請使用者提供或本人跑）。
