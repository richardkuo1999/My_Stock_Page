"""把 Agent 回覆包成可下載的檔案內容（純函式，無網路、無 AI）。

Agent 選 html / markdown 時，handler 不把內容塞進 Telegram 訊息（受 4096 字元
上限），而是產生一份檔案用 reply_document 當附件傳。此模組只負責「產生檔案內容
字串」，實際寫檔與傳送由 handler 處理，方便單元測試。

- build_html_document(): 把 Agent 產出的 HTML 內文包進完整 HTML5 文件 + 內嵌 CSS
  （字體、表格框線、手機 responsive），在瀏覽器/手機開起來就順眼。Agent 此時可用
  完整 HTML（含 <table>、<h1> 等），不受 Telegram 標籤子集限制。
- build_markdown_document(): Markdown 原樣即為檔案內容（.md 本身就是純文字）。
- safe_filename(): 依股票代號/標題組出安全檔名。
"""

from __future__ import annotations

import re

__all__ = [
    "build_html_document",
    "build_markdown_document",
    "safe_filename",
    "title_from_body",
]

# 從內文抓標題用：HTML 第一個 <h1>…</h1>；Markdown 第一個 #~###### 標題行。
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
# 清掉標題內殘留的 HTML 標籤（如 <b>）。
_TAG_RE = re.compile(r"<[^>]+>")

# 內嵌 CSS：無外部相依，離線可讀；行動裝置友善。
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: -apple-system, "PingFang TC", "Microsoft JhengHei",
                 "Noto Sans TC", system-ui, sans-serif;
    line-height: 1.7; max-width: 900px; margin: 0 auto;
    padding: 1.2rem 1rem 3rem; color: #1a1a1a; background: #fff;
    -webkit-text-size-adjust: 100%;
  }}
  h1, h2, h3 {{ line-height: 1.3; }}
  h1 {{ font-size: 1.5rem; border-bottom: 2px solid #2b6cb0; padding-bottom: .3rem; }}
  h2 {{ font-size: 1.25rem; color: #2b6cb0; margin-top: 1.8rem; }}
  table {{
    border-collapse: collapse; width: 100%; margin: 1rem 0;
    font-variant-numeric: tabular-nums;
  }}
  th, td {{ border: 1px solid #cbd5e0; padding: .45rem .7rem; text-align: right; }}
  th {{ background: #edf2f7; }}
  td:first-child, th:first-child {{ text-align: left; }}
  tr:nth-child(even) td {{ background: #f7fafc; }}
  code, pre {{
    font-family: "SF Mono", Menlo, Consolas, monospace;
    background: #f0f0f0; border-radius: 4px;
  }}
  code {{ padding: .1rem .35rem; }}
  pre {{ padding: .8rem; overflow-x: auto; }}
  .footer {{ margin-top: 2.5rem; font-size: .8rem; color: #718096;
             border-top: 1px solid #e2e8f0; padding-top: .8rem; }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e2e8f0; background: #1a202c; }}
    th {{ background: #2d3748; }}
    tr:nth-child(even) td {{ background: #242b38; }}
    th, td {{ border-color: #4a5568; }}
    code, pre {{ background: #2d3748; }}
    h1 {{ border-color: #4299e1; }} h2 {{ color: #63b3ed; }}
  }}
</style>
</head>
<body>
{body}
<div class="footer">由台股投資輔助 Bot 產生 — 僅供參考，非投資建議。</div>
</body>
</html>
"""


def build_html_document(body_html: str, title: str = "台股分析報告") -> str:
    """把 Agent 的 HTML 內文包成完整 HTML5 文件（含 CSS）。

    Args:
        body_html: Agent 產出的 HTML 片段（<body> 內容，可含完整 HTML 標籤）。
        title: 文件標題（顯示在瀏覽器分頁）。

    Returns:
        完整 HTML 文件字串。
    """
    return _HTML_TEMPLATE.format(title=_escape_title(title), body=body_html)


def build_markdown_document(body_md: str) -> str:
    """Markdown 內文即檔案內容，去除首尾多餘空白後回傳。"""
    return body_md.strip() + "\n"


def _escape_title(title: str) -> str:
    """標題只用在 <title> 與檔名場景，做最小 HTML 跳脫。"""
    return (
        title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def safe_filename(stem: str, ext: str) -> str:
    """組出安全檔名：清掉路徑分隔與奇怪字元，限制長度。

    Args:
        stem: 檔名主體（例如「正文科技_4906_分析」）。
        ext: 副檔名，不含點（"html" / "md"）。

    Returns:
        形如 「正文科技_4906_分析.html」的安全檔名。
    """
    stem = stem.strip() or "report"
    # 移除路徑分隔與控制字元；保留中英數、底線、連字號、點。
    stem = re.sub(r"[\\/\x00-\x1f]", "", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem[:60].rstrip("._") or "report"
    return f"{stem}.{ext}"


def title_from_body(body: str, mode: str) -> str:
    """從內文萃取標題當檔名主體，讓附件檔名看得出內容（而非固定 stock_report）。

    Args:
        body: Agent 產出的內文（HTML 片段或 Markdown）。
        mode: "html" → 取第一個 <h1>；"markdown" → 取第一個 # 標題行。

    Returns:
        乾淨的標題字串（已去除內層 HTML 標籤、HTML 實體、多餘空白）；
        找不到標題時回傳空字串，交由呼叫端決定後援檔名。
    """
    if not body:
        return ""

    raw = ""
    if mode == "html":
        m = _H1_RE.search(body)
        if m:
            raw = m.group(1)
    elif mode == "markdown":
        m = _MD_HEADING_RE.search(body)
        if m:
            raw = m.group(1)

    if not raw:
        return ""

    # 去掉標題內殘留 HTML 標籤（<b> 等）、還原常見 HTML 實體、壓平空白。
    text = _TAG_RE.sub("", raw)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()
