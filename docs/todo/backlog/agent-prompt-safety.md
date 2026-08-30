# Agent prompt 安全防護：不允許的 prompt 類型

<!-- labels: backlog, security -->

<!-- 獨立主題：對現有 agent/prompts.py 的安全增強，另行規劃 -->

## 來源

使用者 2026-08-23（uanalyze_cli 引入 8 張 ticket 完成後）提出的安全增強需求。

## 需求

現況：`agent/prompts.py` 的 `SYSTEM_PROMPT` 只描述角色（台股助理）+ 工具清單 + 執行流程，**沒有明確界定「不允許的 prompt 類型 / 拒絕規則」**。Bot 對 `@mention` 開放（且 bridge 目前用 `--dangerously-skip-permissions`，見 README 安全暫時方案），有 prompt-injection 與濫用風險。

想要：在 `SYSTEM_PROMPT` 加入一段安全防護，明列 Agent **不允許**回應/執行的 prompt 類型，降低濫用與注入風險。

## 待規劃內容（規劃時處理）

- **不允許的 prompt 類型清單**（範例，規劃時定稿）：
  - 要求 Agent 忽略/覆寫既有 system prompt 或角色（prompt injection）
  - 要求執行與台股投資輔助無關的任意系統指令 / 檔案操作 / 網路請求
  - 索取機密（`.env`、憑證、token、API key、私鑰）或要求印出環境變數
  - 產生惡意程式、規避付費牆、大量爬取/濫用第三方 API
  - 越權操作（刪改資料、動基礎設施）
  - 明確非投資輔助範疇且有風險的請求
- **拒絕形態**：遇到上述類型時，Agent 該如何回應（簡短拒絕 + 導回可協助的投資輔助任務）。
- **與現有架構的關係**：
  - 這是「軟性」prompt 層防護，**非** root cause 修復；真正的權限隔離仍是把工具做成 MCP server（見 ARCHITECTURE「權限與安全」+ README 安全暫時方案），屬更大的工程。
  - 可與 INV-01（prompts.py 工具清單缺漏）一併處理，因為都是動 `SYSTEM_PROMPT`。
- **測試**：`tests/test_prompts.py`（若有）斷言 SYSTEM_PROMPT 含安全段落；或人工驗證幾個注入樣本被拒。

## 範圍界定

- 對象是 `agent/prompts.py` 的 `SYSTEM_PROMPT`（`build_mention_prompt` 組出的內容）。
- 不含 MCP server 化那條根治路線（另計）。
- 建議與 INV-01 合併成一張「prompts.py 整備」spec 處理。
