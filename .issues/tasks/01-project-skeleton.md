# 01 — 專案骨架 + Bot 啟動

**What to build:** 從零建立專案結構，Bot 能啟動、連上 Telegram polling、收到任何訊息回 echo。Docker 能 build 並成功啟動。所有基礎檔案到位：`main.py`、`requirements.txt`、`.env.example`、`config.json`、`Dockerfile`、`docker-compose.yml`。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `python main.py` 啟動後 Bot 上線，能在 Telegram 收到訊息並回 echo
- [ ] `docker compose up` 能成功啟動
- [ ] 專案目錄結構符合 ARCHITECTURE.md §10（bot/、agent/、tools/、data/）
- [ ] `requirements.txt` 列出所有基礎依賴（python-telegram-bot、APScheduler）
- [ ] `.env.example` 列出所有需要的環境變數
- [ ] `config.json` 有預設的應用設定（vocus_users、排程頻率等）
- [ ] logging 基礎設定（stdout output）
