# 11 — Tool: summarize_document

**What to build:** `tools/summarize_document.py` — 接收 URL 或 PDF 連結，擷取文字內容，透過 Agent 產出摘要，回傳 JSON。這是 /research 功能的核心。

**Blocked by:** 03 — AgentBridge + @mention 觸發

**Status:** ready-for-agent

- [ ] `python tools/summarize_document.py https://example.com/article` 回傳摘要 JSON
- [ ] `from tools.summarize_document import summarize` 可直接 import 使用
- [ ] 支援一般網頁 URL（擷取正文）
- [ ] 支援 PDF URL（下載後擷取文字）
- [ ] 透過 `AgentBridge.send()` 產出摘要
- [ ] 回傳格式：`{"title": "...", "summary": "...", "source_url": "..."}`
- [ ] URL 無法存取時回傳 `{"error": "..."}`
- [ ] 檔頭 docstring 符合規範
- [ ] 有 unit test
