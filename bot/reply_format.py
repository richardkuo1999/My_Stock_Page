"""解析 Agent 回覆的格式標記（純函式，無網路、無 AI）。

Agent 可在回覆「第一行」用 `FORMAT: <mode>` 宣告它想要的呈現方式，讓它自行決定：
  - text     → 純文字 Telegram 訊息（預設）
  - html     → 產生 .html 檔案當附件傳（reply_document）
  - markdown → 產生 .md 檔案當附件傳（reply_document）
handler 依此決定要送訊息還是送檔案。

設計原則：
- 純表現層路由，工具契約與 Agent 邏輯不變。
- 標記可有可無、大小寫不拘、容忍全形冒號；缺標記或無法辨識時一律退回純文字
  （安全預設：純文字絕不會讓 Telegram 送訊息失敗）。
- 只解析並「切掉」第一行標記，不改動其餘內容。
"""

from __future__ import annotations

import re

__all__ = ["parse_reply_format"]

# 允許：行首可有空白 → FORMAT → 半形/全形冒號 → 空白 → mode（大小寫不拘）
_FORMAT_RE = re.compile(
    r"^\s*FORMAT\s*[:：]\s*(html|text|markdown)\s*$", re.IGNORECASE
)


def parse_reply_format(reply: str) -> tuple[str, str]:
    """從 Agent 回覆第一行解析格式標記。

    Args:
        reply: Agent 回傳的完整字串。

    Returns:
        (mode, body)
        - mode: "html" / "markdown" / "text"（無法辨識或缺標記時為 "text"）。
        - body: 切掉標記行後的內容；若第一行不是標記則原樣返回。
    """
    if not reply:
        return "text", reply

    first, sep, rest = reply.partition("\n")
    m = _FORMAT_RE.match(first)
    if not m:
        # 第一行不是格式標記 → 視為純文字，內容原樣不動。
        return "text", reply

    mode = m.group(1).lower()
    # 切掉標記行；rest 可能還有前導換行，去掉一層即可。
    return mode, rest.lstrip("\n") if sep else ""
