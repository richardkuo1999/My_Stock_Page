# 01 — UAnalyzeAuth 認證統一（prefactor 地基）

**What to build:** `tools/uanalyze.py` 擴充單一 `UAnalyzeAuth`：一次 UAnalyze 登入，之後可依 domain 取得三種認證的 request 材料——jwt helper（`api` / `data.twobitto`，Bearer）、cookie helper（`cronjob`，記憶體 4-cookie + Origin/Referer）、gidp helper（`gidp`，寫死公開 GIDP token 常數 + `country=TW`）。這是後續多數功能的共用地基，先做這個「讓後面的改動變簡單」。

**Blocked by:** None — can start immediately.

**Status:** DONE（commit `7ffd66c`，2026-08-23）

- [x] `UAnalyzeAuth` 一次 login 後，jwt/cookie/gidp 三個 helper 各能組出對應 domain 的正確 headers/cookies（`jwt_headers()` / `cookie_context()` / `gidp_headers()`）
- [x] cookie helper 為記憶體組（回傳 dict，不落 CLI cookie 檔）；GIDP token 為模組常數 `GIDP_TOKEN` 並註解「前端 JS 公開寫死」來源
- [x] 現有 `tools/uanalyze.py`（A 套 JWT 分析、report-summaries 監控）行為不變（login 僅新增 token_type/expires_in 兩 assignment，其餘函式未觸碰），原 12 個測試全過
- [x] `tests/test_uanalyze.py` 新增 5 測試：token_type/expires_in 儲存 + 三 helper 形態（含 gidp 不誤用 access_token 防呆 + token_type None 邊角）
- [x] 全套測試綠：**267 passed**（原 262 + 5 新，協調者獨立跑過）

## 已知小邊角（供 ticket 05 留意，不阻斷）
`cookie_context()` 的 `expires_in` 用 `str(self.expires_in)`；若 `expires_in` 為 None 會變字串 `"None"`。實務上 login 成功必帶 4 欄（findings 實證），且 helper 前提是已登入，故非實務路徑。ticket 05 真正用 cookie_context 打 cronjob 時若要更嚴謹可加 None 防護。
