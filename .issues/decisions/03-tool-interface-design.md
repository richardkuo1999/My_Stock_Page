# Agent Tool 定義與介面規範

<!-- labels: wayfinder:grilling -->
<!-- parent: map -->
<!-- blocked-by: (none — unblocked) -->
<!-- assigned: kiro -->
<!-- status: closed -->

## Question

Agent 能呼叫的 tool 怎麼定義？介面規範是什麼？

需要決定：
1. **Tool 暴露方式**：Python function 直接被 Agent call？MCP server？REST endpoint？Antigravity 的原生 tool 定義格式？
2. **Tool 清單**：從保留功能推導出 Agent 需要哪些 tool（stock_analyze、fetch_news、volume_spike、draw_kchart、uanalyze、research_doc...）
3. **Input/Output schema**：每個 tool 的參數和回傳格式怎麼定義？
4. **共用性**：Python Bot 的 /command handler 跟 Agent tool 能否共用同一份 service 層？（避免邏輯寫兩份）
5. **未來可換**：Tool 定義要跟 Antigravity 綁多深？如果換框架，tool 能不能直接搬？

## Resolution

### Tool 暴露方式：獨立 Python script + docstring 描述

- 不用 MCP server，不用額外 process
- Agent（CLI headless）有 shell 存取能力，直接讀 `tools/` 目錄的 script 檔頭 docstring 了解用途
- Agent 自行決定要跑哪個 script、帶什麼參數
- 每個 script 檔頭有標準 docstring：工具名、用法、回傳格式

```python
"""fetch_news — 取得指定股票的最新新聞
用法: python tools/fetch_news.py 2330 [--limit 5]
回傳: JSON {"articles": [{title, source, date, url, summary}]}
"""
```

### Tool 清單（6 個）

| Script | 功能 |
|--------|------|
| `tools/fetch_news.py` | 抓指定股票新聞 |
| `tools/uanalyze.py` | AI 估值分析 |
| `tools/get_stock_price.py` | 即時股價 |
| `tools/draw_kchart.py` | 畫 K 線圖（回傳圖片路徑） |
| `tools/fetch_threads.py` | 抓追蹤帳號的 Threads 貼文 |
| `tools/summarize_document.py` | URL/PDF 文件摘要 |

### Output 格式：統一 stdout JSON

- 所有 script 的 stdout 都是 JSON
- 圖片類回傳 `{"image_path": "/path/to/file.png"}`
- 錯誤回傳 `{"error": "描述"}` + 非零 exit code

### 共用性：一份邏輯，雙入口

```python
# tools/check_volume_spike.py
"""check_volume_spike — 掃描爆量股票
用法: python tools/check_volume_spike.py [SYMBOL | --scan-all]
回傳: JSON array of {symbol, volume, avg_volume, ratio}
"""

async def scan_all() -> list[dict]:
    # 核心邏輯
    ...

async def check(symbol: str) -> dict:
    ...

if __name__ == "__main__":
    import json, asyncio, sys
    result = asyncio.run(scan_all() if "--scan-all" in sys.argv else check(sys.argv[1]))
    print(json.dumps(result, ensure_ascii=False))
```

- **Agent 用 CLI**：`python tools/check_volume_spike.py 2330` → stdout JSON
- **Bot 排程用 import**：`from tools.check_volume_spike import scan_all`
- 同一份邏輯，不寫兩次

### 框架綁定度：零

- Tool 定義不依賴 Antigravity 任何 protocol
- 就是普通 Python script，任何 Agent 框架都能跑
- 換框架只需要讓新框架知道 `tools/` 目錄在哪、怎麼執行

### 安全性

- Agent 有 shell 權限（私人 bot，可接受）
- script 只做讀取 + 計算，不做刪除/寫入操作
