# Bot ↔ Agent 指令分工邊界

<!-- labels: wayfinder:grilling -->
<!-- parent: map -->
<!-- assigned: kiro -->
<!-- status: closed -->

## Question

保留的每個功能（估值、新聞推播、爆量偵測、UAnalyze、Threads、K線圖、/research），各自應該走哪條路？

需要決定：
1. 哪些指令**只走 Python**（純確定性，不需 AI）
2. 哪些指令**只走 Agent**（需要 AI 推理 / 多 tool 組合）
3. 哪些**兩條路都能走**（/command 是快捷、@agent 是彈性版）
4. 排程推播屬於哪一側？（應該是 Python，但推播內容是否需要 Agent 參與？）

這張票的答案直接決定 Python Bot 要實作多少 handler、Agent 要註冊多少 tool。

## Resolution

### 架構三層分工

| 層 | 職責 | 觸發方式 |
|---|------|---------|
| **Telegram Bot (Python)** | 收訊息、判斷是否觸發 Agent、跑排程、管理訂閱、推播 | 所有 Telegram 訊息先到這 |
| **Agent (Antigravity)** | 理解意圖、路由 tool、生成回應、新聞摘要 | 被 Bot 轉發（需關鍵詞/tag 觸發） |
| **Tools (.py)** | 純邏輯（股票分析、抓新聞、爆量掃描、畫圖等） | 被 Agent 呼叫 |

### Agent 觸發條件

用戶訊息需含關鍵詞或 Telegram tag 才轉發 Agent，避免過量使用 token。

### Bot 直接處理（不經 Agent）：
- `/sub_ispike`, `/unsub_ispike` 等訂閱管理指令
- 排程執行本身
- 爆量推播（直推數據表格）
- Threads 推播（直推貼文內容）

### 經 Agent 處理：
- 所有帶關鍵詞/tag 的用戶訊息（Agent 自主決定用哪些 tool）
- 新聞推播內容（排程抓完新聞 → 轉 Agent 摘要 → 再推播）

### 沒有傳統 /command 了
- 舊版的 `/esti`, `/spike`, `/k`, `/p`, `/ua`, `/news`, `/research` 等功能性指令全部移除
- 用戶直接用自然語言 + tag 對 Agent 說話，Agent 路由到對應 tool
- 只保留排程訂閱管理指令（`/sub_*`, `/unsub_*`）

### Tools 設計原則
- 各功能寫成獨立 `.py` 檔，從 old_file services 精簡搬入
- Tool 是純邏輯，不綁定 AI 框架，未來換 Agent 只需換 bridge 層

### 待研究（開 research ticket）
- Antigravity 怎麼註冊自定義 tool
- Telegram Bot 偵測 @mention / 關鍵詞的機制
- Agent 能否被程式化呼叫（排程新聞摘要場景）
