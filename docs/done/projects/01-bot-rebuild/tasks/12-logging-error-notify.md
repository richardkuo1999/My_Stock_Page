# 12 — Logging + 錯誤通知

**What to build:** 完整的 logging 設定和排程 job 錯誤通知機制。stdout + file rotation + 連續失敗時推 Telegram 通知管理者。

**Blocked by:** 01 — 專案骨架 + Bot 啟動

**Status:** done

- [x] logging config：DEBUG/INFO → stdout，WARNING/ERROR → stdout + `data/logs/bot.log`
- [x] log 檔案 rotation（按大小或日期）
- [x] `data/logs/` 目錄自動建立
- [x] 排程 job 失敗自動 retry 1-2 次
- [x] 連續失敗（retry 仍失敗）→ 推 Telegram 通知 `TELEGRAM_ADMIN_CHAT_ID`
- [x] 通知訊息包含：job 名稱、錯誤摘要、失敗次數
- [x] 有 unit test（mock Telegram send，驗證通知邏輯）
