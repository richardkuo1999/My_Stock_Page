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

# 「像正文的行」＝停手信號。標記前若出現任何一行帶有結構化標記特徵（HTML 標籤、
# Markdown 標題/表格/條列/引用），就不再把後續當前言，避免把真正內文誤判成旁白。
# 只有「純自然語言旁白句」（不含這些特徵）才算標記前可丟棄的前言。
_BODY_LIKE_RE = re.compile(
    r"</?[a-zA-Z][^>]*>"        # HTML 標籤 <h1> </p> <table ...>
    r"|^\s*#{1,6}\s"            # Markdown 標題 # ~ ######
    r"|\|"                      # Markdown 表格（含 | ）
    r"|^\s*(?:[-*>]\s|\d+\.\s)"  # 條列 - * / 引用 > / 有序 1.
)


def parse_reply_format(reply: str) -> tuple[str, str]:
    """從 Agent 回覆開頭解析格式標記。

    容忍常見的 LLM 雜訊：標記前的空白行、把整段回覆包起來的 code fence
    （```／~~~，可含語言名），以及標記前**任意行數的前言/進度旁白**（如「請稍候…」
    「好的，以下是報告：」「I will wait for … to finish.」——實測 Agent 常自作主張
    在最終回覆前堆一疊等待/思考旁白）。

    判準（不看行數，看內容）：從頭逐行掃描，直到遇到 FORMAT 標記就採用該格式並
    丟棄它前面的所有前言；但只要在標記**之前**先遇到「像正文的行」（帶 HTML 標籤或
    Markdown 標題/表格/條列/引用等結構特徵，見 `_BODY_LIKE_RE`），就停手判為純文字。
    這樣不論前言幾行都能救回，又能擋掉「正文中段剛好出現一行 FORMAT」的誤判——因為
    正文特徵行會先觸發停手。

    Args:
        reply: Agent 回傳的完整字串。

    Returns:
        (mode, body)
        - mode: "html" / "markdown" / "text"（無法辨識或缺標記時為 "text"）。
        - body: 切掉標記行（含其前的前言/前導 fence、與包裹用的收尾 fence）後的內容；
          非標記時原樣返回。
    """
    if not reply:
        return "text", reply

    lines = reply.split("\n")
    saw_fence = False

    # 逐行掃描找標記：容忍空白行、（至多一層）開頭 fence、任意行數的旁白前言；
    # 一旦遇到「像正文的行」就停手（判 text），避免把真正內文當前言丟掉。
    marker_idx = -1
    for i, line in enumerate(lines):
        if line.strip() == "":
            continue
        if not saw_fence and _FENCE_RE.match(line):
            saw_fence = True
            continue
        if _FORMAT_RE.match(line):
            marker_idx = i
            break
        if _BODY_LIKE_RE.search(line):
            # 標記前先出現正文特徵 → 不是「標記+內文」結構，安全判純文字。
            break
        # 其餘：純自然語言旁白句 → 當前言，跳過繼續找。

    if marker_idx < 0:
        return "text", reply

    mode = _FORMAT_RE.match(lines[marker_idx]).group(1).lower()

    body_lines = lines[marker_idx + 1 :]

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
