# 10 — Tool: uanalyze

**What to build:** `tools/uanalyze.py` — 查詢 UAnalyze AI 估值分析，回傳 JSON。含 JWT 認證（帳密登入 → token → 自動 refresh）。從舊版 `uanalyze_ai.py` 搬移並改寫認證機制。

**Blocked by:** 01 — 專案骨架 + Bot 啟動

**Status:** done

- [x] `python tools/uanalyze.py 2330` 回傳估值分析 JSON
- [x] `from tools.uanalyze import analyze` 可直接 import 使用
- [x] 啟動時用 `UANALYZE_EMAIL` + `UANALYZE_PASSWORD` POST `/auth/token` 取 JWT
- [x] Request header 帶 `Authorization: Bearer {access_token}`
- [x] Token 過期自動呼叫 `/auth/token/refresh` 換新 token
- [x] 支援 completions API（prompt + ticker）和 report-summaries API
- [x] 認證失敗時回傳明確錯誤
- [x] 檔頭 docstring 符合規範
- [x] 有 unit test（mock auth + API response）
