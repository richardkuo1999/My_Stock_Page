# 03 — AgentBridge + @mention 觸發

**What to build:** 用戶在 Telegram @bot_name 時，Bot 偵測到 mention，提取文字後透過 `AntigravityCLIBridge` 送給 Antigravity CLI headless，將 Agent 回覆轉發回 Telegram。含超時和錯誤處理。

**Blocked by:** 01 — 專案骨架 + Bot 啟動

**Status:** done

- [x] `agent/bridge.py` 定義 `AgentBridge` ABC（`send`、`is_available` 方法）
- [x] `AntigravityCLIBridge` 實作：`asyncio.create_subprocess_exec` 呼叫 `agy -p`
- [x] Bot 偵測 `MessageEntity.MENTION`，提取 @bot_name 後的文字
- [x] 成功時將 Agent 回覆發回 Telegram
- [x] 超時（可設定秒數）時回覆「Agent 暫時無法回應，請稍後再試」
- [x] exit code 非 0 時回覆錯誤訊息
- [x] `is_available()` 檢查 agy 是否可執行
- [x] 有 unit test（mock subprocess）
