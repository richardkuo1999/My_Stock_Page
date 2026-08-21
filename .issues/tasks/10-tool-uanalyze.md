# 10 — Tool: uanalyze

**What to build:** `tools/uanalyze.py` — 查詢 UAnalyze AI 估值分析，回傳 JSON。含 JWT 認證（帳密登入 → token → 自動 refresh）。從舊版 `uanalyze_ai.py` 搬移並改寫認證機制。

**Blocked by:** 01 — 專案骨架 + Bot 啟動

**Status:** ready-for-agent

- [ ] `python tools/uanalyze.py 2330` 回傳估值分析 JSON
- [ ] `from tools.uanalyze import analyze` 可直接 import 使用
- [ ] 啟動時用 `UANALYZE_EMAIL` + `UANALYZE_PASSWORD` POST `/auth/token` 取 JWT
- [ ] Request header 帶 `Authorization: Bearer {access_token}`
- [ ] Token 過期自動呼叫 `/auth/token/refresh` 換新 token
- [ ] 支援 completions API（prompt + ticker）和 report-summaries API
- [ ] 認證失敗時回傳明確錯誤
- [ ] 檔頭 docstring 符合規範
- [ ] 有 unit test（mock auth + API response）
