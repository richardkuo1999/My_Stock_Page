# Agent 接入方式與抽象層設計

<!-- labels: wayfinder:grilling -->
<!-- parent: map -->
<!-- blocked-by: (none — unblocked) -->
<!-- assigned: kiro -->
<!-- status: closed -->

## Question

Python Bot 要怎麼跟 Antigravity Agent 通訊？抽象層怎麼設計才能未來換掉 Antigravity？

需要決定：
1. **接入機制**：用 CDP（像 antigravity-telegram-suite）？還是 Antigravity 有提供 HTTP API / CLI？還是透過 stdin/stdout？
2. **抽象介面**：Python 端定義一個 `AgentBridge` interface，換 AI 框架時只要換 implementation？
3. **訊息格式**：Bot 轉發給 Agent 的 payload 長什麼樣？純文字？structured message（含 context）？
4. **回應處理**：Agent 回來的是 streaming？一次性？怎麼轉成 Telegram 訊息？
5. **錯誤處理**：Agent 掛了 / 回應太慢，Bot 怎麼 fallback？

## Resolution

### 接入機制：Antigravity CLI Headless Mode（subprocess）

- 用 `agy -p "prompt" --output-format json` 單次呼叫
- Python 透過 `subprocess` 或 `asyncio.create_subprocess_exec` 驅動
- 認證用 CLI 登入 session（Google AI Pro 方案不提供 API key，SDK 無法使用）

**為什麼不用 SDK：** `google-antigravity` SDK 需要 `GEMINI_API_KEY`，Google AI Pro 方案不提供。未來如果取得 API key，可以切到 SDK。

**為什麼不用 CDP：** CLI headless 是官方支援的穩定 API，不依賴 GUI，不是 hack。

### 抽象層：正式 interface（AgentBridge ABC）

```python
from abc import ABC, abstractmethod

class AgentBridge(ABC):
    @abstractmethod
    async def send(self, prompt: str) -> str:
        """送 prompt 給 Agent，回傳純文字回應"""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """檢查 Agent 是否可用"""
        ...
```

實作：
- `AntigravityCLIBridge` — 現在用，call `agy -p`
- 未來可加 `AntigravitySDKBridge` — 有 API key 時切換

呼叫端只認 `AgentBridge` interface，換框架不改呼叫端。

### 對話模式：無狀態，每次獨立

- 不保留多輪 context
- 每次 `@agent` 訊息都是獨立的一問一答
- 省 token、簡單、不需管理 session

### 訊息格式：純文字 prompt

- Bot 把用戶訊息（去掉 @tag 後的文字）直接作為 prompt 傳給 Agent
- 不需要 structured payload

### 回應處理：一次性 JSON

- `--output-format json` 回傳完整 JSON envelope
- 取 `response` 欄位作為回覆文字
- 發回 Telegram（如果太長則分段）

### 錯誤處理：告知用戶

- 超時（`--print-timeout`）→ 告訴用戶「Agent 暫時無法回應，請稍後再試」
- exit code 非 0 → 同上
- 不做 fallback

### 架構圖

```
Telegram 用戶
    │ @agent 估值 2330
    ▼
Python Bot (MessageHandler)
    │ 偵測 @mention → 提取文字
    ▼
AgentBridge.send("估值 2330")
    │
    ▼
AntigravityCLIBridge
    │ subprocess: agy -p "估值 2330" --output-format json
    ▼
Antigravity CLI (headless)
    │ 使用已登入的 Pro 方案額度
    │ 可呼叫 MCP tools（股票分析、新聞等）
    ▼
JSON response → 取 .response
    │
    ▼
Bot 發回 Telegram
```
