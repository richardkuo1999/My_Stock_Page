# 調查 uanalyze_cli 三套認證機制與統一可行性

<!-- labels: wayfinder:research -->
<!-- parent: map-uanalyze-cli -->
<!-- blocks: ua-02-auth-decision -->

**Type:** research (AFK)
**Status:** ✅ closed（research subagent 已完成，findings: `research/ua-auth/findings.md`）

## Resolution（2026-08-22）

三套認證事實（皆 cited 到 `research/ua-auth/findings.md`）：

- **A JWT Bearer** — auth `api.uanalyze.com.tw` + 資料 `data.uanalyze.twobitto.com`；header `Authorization: Bearer <token>`；帳密登入 `/auth/token`。**現有 tools/uanalyze.py 就是這套，domain 完全一致。**
- **B Session cookie** — `cronjob.uanalyze.com.tw`；`requests.Session` 帶 `access_token` cookie（不帶 header）；A3–A9 全用它。
- **C 寫死 GIDP token** — `gidp.uanalyze.com.tw`；`Authorization: Bearer tquEQ...`（前端 JS 寫死固定公開常數，非登入產生）；WebStockInfo/StockPool 用。

**決定性發現：** 實測 decode 現存快取檔，B 的 cookie `access_token` 與 A 的 JWT `access_token` **byte-for-byte 完全相同**（同一次登入產生，sub=145820）。→ A+B 本質同一個 token，差別只在「放 header」vs「放 cookie」。

**能否統一結論：**
- A+B 極可能統一成 JWT Bearer（同一 token）。**唯一缺口**：未實測 `cronjob.uanalyze.com.tw` 是否接受 Bearer header（現況只用 cookie）→ 需一次 online 唯讀驗證。
- C（GIDP）是不同 domain 的固定 API-key，非 JWT。能否改吃 JWT 未知未驗證。

## Question

`uanalyze_cli` 用了三套不同的 UAnalyze 認證，現有 `tools/uanalyze.py` 只用其中一套（JWT）。調查清楚三套的實際行為與能否統一，產出事實供後續認證決策：

1. **JWT Bearer**（`/auth/token` + `/auth/token/refresh`）— 現有 `tools/uanalyze.py` 用；uanalyze_cli 的 A1/A2/A10（completions、report-summaries）也用。確認：base URL、header 格式、refresh 流程。
2. **Session cookie**（`uanalyze_session_cookies.json`，含 `access_token` cookie）— uanalyze_cli 的 `get_eps.py` 對 `data_fetch/api/{Module}/{ticker}`（A3–A9）用。確認：cookie 從哪來（`ensure_token_and_login` / `login_with_password`）、domain、與 JWT 是否同一組帳密登入產生、能否改用 JWT Bearer 打同一批端點。
3. **寫死 GIDP token**（`GIDP_TOKEN = "tquEQ..."`，`gidp.uanalyze.com.tw/data_fetch/api/StockPool`）— 抓全台股名對照。確認：是否公開固定、會不會過期。

**要回答的核心：** 這三套能否收斂成一套（理想是全用現有 JWT Bearer）？各端點的 domain（`DATA_API_DOMAIN` / `GIDP_API_DOMAIN` / auth domain）分別是什麼？哪些端點只能用 cookie、哪些能用 JWT？

**產出：** 一份 cited 事實摘要（各認證的 domain/header/流程/可統一性），寫到 `research/ua-auth/` 供認證決策 ticket 參考。**不做決策、不寫實作。**

**來源檔案：** `stocktool/uanalyze_cli/get_eps.py`（認證區 line 30–320）、`stocktool/uanalyze_cli/uanalyze_cli.py`（`get_valid_token` line 82）、現有 `tools/uanalyze.py`（`_request_with_auth`、`_auth`）
