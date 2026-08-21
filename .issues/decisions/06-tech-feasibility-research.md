# Antigravity + Telegram 技術可行性調查

<!-- labels: wayfinder:research -->
<!-- parent: map -->
<!-- assigned: kiro -->
<!-- status: closed -->

## Question

確認新架構的三個技術關鍵點是否可行：

1. **Antigravity 自定義 tool 註冊**：Antigravity Agent 怎麼註冊外部 .py 檔作為 tool？格式是什麼？有沒有官方文件或範例？
2. **Telegram Bot @mention 偵測**：python-telegram-bot 能否偵測 group 裡的 @bot_name mention 或特定關鍵詞，作為轉發 Agent 的 trigger？
3. **Agent 程式化呼叫**：排程新聞摘要場景——不是人在 Telegram 打字觸發，而是 Python 排程 job 主動把內容丟給 Agent 做摘要——Antigravity 支援這種 headless / API 呼叫嗎？還是只能透過 CDP 模擬輸入？

調查來源：Antigravity 官方文件、antigravity-telegram-suite repo、python-telegram-bot docs。

## Resolution

### 1. Antigravity 自定義 Tool 註冊 — ✅ 可行（透過 MCP）

Antigravity 支援 **Model Context Protocol (MCP)**。設定方式：

- 設定檔位置：`~/.gemini/antigravity/mcp_config.json`（macOS: `~/.gemini/antigravity/mcp_config.json`）
- 在 IDE 內：三點選單 → MCP Servers → Manage MCP Servers → View raw config
- 格式範例：

```json
{
  "mcpServers": {
    "stock-tools": {
      "command": "python",
      "args": ["/path/to/stock_tools_mcp_server.py"],
      "env": {}
    }
  }
}
```

**這代表什麼：**
- 你的各功能 .py 檔可以寫成 **MCP server**（使用 Python MCP SDK），以 stdio 方式跟 Antigravity 通訊
- Agent 會看到你註冊的 tool，可以自主決定何時呼叫
- 這是官方支援的方式，不是 hack
- 多個 MCP server 可以同時註冊（股票分析 server、新聞 server、圖表 server 各自獨立）

**對架構的影響：**
- Tool 層用 Python MCP SDK 寫（如 `mcp` 套件）
- 每個 tool 暴露 function schema（name、description、parameters）
- 未來換 AI 框架，只要新框架也支援 MCP（Claude、Cursor 等都支援），tool 可以直接搬

### 2. Telegram Bot @mention 偵測 — ✅ 完全可行

python-telegram-bot 原生支援：

```python
from telegram import MessageEntity

async def handle_message(update, context):
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == MessageEntity.MENTION:
                mentioned = update.message.text[entity.offset:entity.offset + entity.length]
                if mentioned == "@your_bot_name":
                    # 轉發給 Agent
                    text = update.message.text.replace("@your_bot_name", "").strip()
                    await forward_to_agent(text)
```

- `MessageEntity.type == 'mention'` 偵測 @username
- 在 group chat 中完全支援
- 也可以用 `MessageHandler` + filter 做更精細的控制
- 關鍵詞觸發也可以用 `filters.Regex` 實作

### 3. Agent 程式化呼叫（排程場景）— ✅ 可行，有兩條路

**方式 A：CDP 注入（antigravity-telegram-suite 方式）**

`sendViaCDP(text, port)` 函式可以從外部程式注入訊息到 Antigravity 的聊天輸入框：
- 找到 Antigravity 的 CDP target（透過 `http://127.0.0.1:{port}/json`）
- 透過 `Runtime.evaluate` 把文字填入 editor、模擬 Enter
- Python 排程 job 可以呼叫 Node.js script 或直接用 Python CDP client

**方式 B：MCP send_prompt（antigravity-mcp-experimental 方式）**

`antigravity-mcp-experimental` extension 提供 `send_prompt` MCP tool：
- 外部腳本可以透過 stdio proxy（`node bin/stdio-proxy.mjs`）發送 prompt 到 active chat
- 不需要 CDP port（寫入不需要，讀取才需要）
- 更乾淨的 API

**共同限制：**
- ⚠️ **Antigravity IDE/App 必須在運行中** — 沒有真正的 headless mode
- 必須有 GUI 環境（或至少 virtual display）
- 部署環境必須能跑 Antigravity Desktop App

**對架構的影響：**
- 新聞推播排程：Python job 抓新聞 → 呼叫 `send_prompt`（or CDP）把內容丟給 Agent → Agent 摘要 → Agent 呼叫「推播 tool」把摘要發到 Telegram
- 或者更簡單：Python job 抓新聞 → 直接呼叫 Gemini API 做摘要（但你說沒有 API key）
- 所以需要 Antigravity 持續運行作為「AI 引擎」

### Summary

| 問題 | 可行？ | 方式 | 風險/限制 |
|------|--------|------|-----------|
| Tool 註冊 | ✅ | MCP server（官方支援，stdio/HTTP） | 官方功能，低風險 |
| @mention 偵測 | ✅ | MessageEntity.MENTION | 原生支援，無風險 |
| 程式化呼叫 Agent | ✅ | **Antigravity CLI Headless Mode** | **不需要 GUI！完全 headless 部署** |

### ⚠️ 重大修正（基於官方文件 antigravity.google/docs）

之前的結論「需要 Antigravity Desktop App 持續運行 + GUI」是**錯的**。

**Antigravity CLI** (`agy`) 提供完整的 **Headless Mode**（官方文件：https://antigravity.google/docs/cli/headless/）：

- `agy -p "prompt"` — 單次非互動式呼叫，輸出到 stdout
- `--output-format json` — 結構化 JSON 輸出
- `--input-format stream-json` — 持續 session，透過 stdin 送 prompt
- **Python 可直接用 subprocess 驅動**：

```python
import json, subprocess

proc = subprocess.Popen(
    ["agy", "--input-format", "stream-json", "--output-format", "stream-json"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
)

def ask(prompt):
    message = {"event": "user", "message": {"content": prompt}}
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()
    for line in proc.stdout:
        event = json.loads(line)
        if event["event"] == "result":
            return event["result"]["response"]
```

- 支援 MCP tool（CLI 也有 MCP 設定）
- 支援 `--dangerously-skip-permissions` 全自動模式
- 不需要 GUI，純終端程式

### 對架構的影響（修正）

| 原本理解 | 修正後 |
|---------|--------|
| 需要 Desktop App + GUI | CLI headless mode 即可，純終端 |
| 只能透過 CDP 模擬輸入 | subprocess + stdin/stdout 官方 API |
| 部署需要 virtual display | 任何有終端的環境都能跑 |
| 程式化呼叫靠 hack | 官方支援的 headless mode |

### MCP 官方設定（確認）

設定檔位置：
- 全域：`~/.gemini/config/mcp_config.json`
- Workspace：`.agents/mcp_config.json`

```json
{
  "mcpServers": {
    "stock-tools": {
      "command": "python",
      "args": ["/path/to/stock_tools_mcp_server.py"],
      "env": {}
    }
  }
}
```

來源：https://antigravity.google/docs/mcp/
