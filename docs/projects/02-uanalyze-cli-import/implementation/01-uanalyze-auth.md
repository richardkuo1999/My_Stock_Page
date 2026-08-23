# 01 — UAnalyzeAuth 認證統一（prefactor 地基）

**What to build:** `tools/uanalyze.py` 擴充單一 `UAnalyzeAuth`：一次 UAnalyze 登入，之後可依 domain 取得三種認證的 request 材料——jwt helper（`api` / `data.twobitto`，Bearer）、cookie helper（`cronjob`，記憶體 4-cookie + Origin/Referer）、gidp helper（`gidp`，寫死公開 GIDP token 常數 + `country=TW`）。這是後續多數功能的共用地基，先做這個「讓後面的改動變簡單」。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `UAnalyzeAuth` 一次 login 後，jwt/cookie/gidp 三個 helper 各能組出對應 domain 的正確 headers/cookies（實測 A 的 JWT 與 B 的 cookie access_token 相同，共用一次 login）
- [ ] cookie helper 為記憶體組（不落 CLI cookie 檔）；GIDP token 為模組常數並註解「前端公開寫死」來源
- [ ] 現有 `tools/uanalyze.py`（A 套 JWT 分析、report-summaries 監控）行為不變，回歸測試通過
- [ ] `tests/test_uanalyze.py` 新增：mock login → 斷言三 helper 各組出正確認證形態
- [ ] 全套測試綠
