# Analysis Bot 重生：AI Agent + Telegram 混合架構 spec

<!-- labels: wayfinder:map -->

## Destination

產出一份「新專案架構 spec」——混合架構（Python Telegram Bot + Antigravity Agent），決定好邊界、接入方式、tool 設計、排程、資料層、部署拓撲、專案骨架，交付給實作。

## Notes

- 領域：台股投資輔助 Telegram Bot
- 雙觸發設計：`/command` 走 Python（省 token、確定性）、`@agent` 轉發 Antigravity（靈活組合 tool）
- 排程推播由背景 Python 服務負責
- AI 框架目前用 Antigravity（CDP），但架構要考慮未來可換
- 全新 repo，從 `old_file/` 挑 service 搬入
- 每個 session 應諮詢 /grilling 和 /domain-modeling skills

## Blocking edges

```
[Bot ↔ Agent 指令分工邊界] ──blocks──► [Agent 接入方式與抽象層設計]
[Bot ↔ Agent 指令分工邊界] ──blocks──► [排程與推播架構]
[Agent 接入方式與抽象層設計] ──blocks──► [Agent Tool 定義與介面規範]
[Antigravity + Telegram 技術可行性調查] ──blocks──► [Agent 接入方式與抽象層設計]
[Antigravity + Telegram 技術可行性調查] ──blocks──► [Agent Tool 定義與介面規範]
```

**Frontier（現在可以開工的）：**
（原始 6 張 ticket 全部 closed — 進入 fog graduation 階段）

**Blocked（等前置決定完才能動）：**
（無）

## Decisions so far

<!-- one line per closed ticket: gist + link -->

- [Bot ↔ Agent 指令分工邊界](tickets/01-bot-agent-boundary.md) — 三層架構（Bot 薄殼 + Agent 路由 + Tools .py）；無傳統 /command，用戶自然語言 + tag 觸發 Agent；排程訂閱指令留在 Bot；新聞推播經 Agent 摘要
- [Antigravity + Telegram 技術可行性調查](tickets/06-tech-feasibility-research.md) — 三項皆可行：Tool 用 MCP server 註冊（官方）；@mention 用 MessageEntity 偵測；程式化呼叫用 **Antigravity CLI Headless Mode**（不需 GUI，純終端 subprocess 驅動）
- [Agent 接入方式與抽象層設計](tickets/02-agent-bridge-design.md) — CLI headless subprocess（Pro 方案無 API key 不能用 SDK）；AgentBridge ABC 抽象層；無狀態一問一答；錯誤直接告知用戶
- [Agent Tool 定義與介面規範](tickets/03-tool-interface-design.md) — 獨立 Python script + docstring，Agent 讀檔自己跑；6 個 tool（爆量偵測已移除）；統一 stdout JSON；Bot 排程直接 import 同一份；零框架綁定
- [排程與推播架構](tickets/04-scheduler-architecture.md) — APScheduler 同 process；新聞經 Agent 摘要、Threads 直推；retry + 通知管理者；新聞每小時、Threads 每 15 分
- [資料層設計](tickets/05-data-layer-design.md) — JSON 檔案（不用 DB）；存訂閱 + 已推 ID；新聞 7 天 TTL、Threads 3 天 TTL 自動清理；Agent 不碰資料層

## Fog Graduation（補充決定）

- **部署**：Docker + 本機直跑雙支援；`Dockerfile` + `docker-compose.yml`
- **新聞來源**：砍 Google News TW（1 個），保留其餘 15 個（含 Vocus 特定作者、UDN 財經版、Pocket 學堂、Buffett Letters、Howard Marks Memos）
- **Threads 追蹤**：改用 Threads 官方 API（取代 Playwright 爬蟲）；需 Meta Developer App + access token
- **新聞 ID**：用 URL 作為唯一識別
- **監控/Logging**：Python logging → stdout + log 檔 rotation（`data/logs/`）；critical 推 Telegram 通知管理者

## Not yet specified

<!-- fog of war — all graduated -->

（全部已決定）

## Out of scope

<!-- work beyond the destination — never graduates -->

- Web 儀表板（已砍）
- 情緒分析 /senti（已砍）
- 每日自動分析 + 低估偵測（已砍）
- MEGA 下載（已砍）
- Podcast 摘要（已砍）
- /chat AI 對話（已砍，由 @agent 取代）
- 自選股管理 /watch（已砍）
- 實際實作 / coding（這是 planning map，不做 build）
