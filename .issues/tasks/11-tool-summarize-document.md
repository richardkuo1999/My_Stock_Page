# 11 — Tool: summarize_document

**What to build:** `tools/summarize_document.py` — 接收 URL 或 PDF 連結，擷取文字內容，透過 Agent 產出摘要，回傳 JSON。這是 /research 功能的核心。

**Blocked by:** 03 — AgentBridge + @mention 觸發

**Status:** done

- [x] `python tools/summarize_document.py https://example.com/article` 回傳摘要 JSON
- [x] `from tools.summarize_document import summarize` 可直接 import 使用
- [x] 支援一般網頁 URL（擷取正文）
- [x] 支援 PDF URL（下載後擷取文字）
- [x] 透過 `AgentBridge.send()` 產出摘要
- [x] 回傳格式：`{"title": "...", "summary": "...", "source_url": "..."}`
- [x] URL 無法存取時回傳 `{"error": "..."}`
- [x] 檔頭 docstring 符合規範
- [x] 有 unit test
