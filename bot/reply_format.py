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

# 一行只有 code fence（```、~~~，後面可跟語言名如 ```html）。Agent 常把整段
# 回覆包在 fence 裡，或在標記前留空行/fence，這些都不該讓標記失效。
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)[a-zA-Z0-9]*\s*$")


def parse_reply_format(reply: str) -> tuple[str, str]:
    """從 Agent 回覆開頭解析格式標記。

    容忍常見的 LLM 雜訊：標記前的空白行、以及把整段回覆包起來的 code fence
    （```／~~~，可含語言名）。只要在這些雜訊之後、真正內文之前出現 FORMAT 標記
    即算數；若標記前有實質文字（非空白、非 fence）則視為純文字，內容原樣返回。

    Args:
        reply: Agent 回傳的完整字串。

    Returns:
        (mode, body)
        - mode: "html" / "markdown" / "text"（無法辨識或缺標記時為 "text"）。
        - body: 切掉標記行（與包裹用的前導/收尾 fence）後的內容；
          非標記時原樣返回。
    """
    if not reply:
        return "text", reply

    lines = reply.split("\n")
    saw_fence = False
    idx = 0

    # 跳過標記前的空白行與（至多一層）開頭 code fence。
    while idx < len(lines):
        line = lines[idx]
        if line.strip() == "":
            idx += 1
            continue
        if not saw_fence and _FENCE_RE.match(line):
            saw_fence = True
            idx += 1
            continue
        break

    if idx >= len(lines) or not _FORMAT_RE.match(lines[idx]):
        # 標記前有實質內容或根本沒有標記 → 純文字，原樣不動。
        return "text", reply

    mode = _FORMAT_RE.match(lines[idx]).group(1).lower()

    body_lines = lines[idx + 1 :]

    # 若開頭吃掉一層 fence，對應把收尾 fence 也切掉（若存在）。
    if saw_fence:
        for j in range(len(body_lines) - 1, -1, -1):
            if body_lines[j].strip() == "":
                continue
            if _FENCE_RE.match(body_lines[j]):
                body_lines = body_lines[:j]
            break

    body = "\n".join(body_lines).lstrip("\n").rstrip()
    return mode, body
