"""
爆量偵測 Telegram：一次列出全部結果（過長時依 SPIKE_TABLE_CHUNK 拆成多則「續」訊息）。

使用 HTML + <pre>，避免舊版 Markdown 對括號、底線等字元解析失敗。
"""

from __future__ import annotations

import html

from .volume_spike_formatter import (
    SPIKE_TABLE_CHUNK,
    format_spike_row,
    get_table_header,
)
from .volume_spike_scanner import VolumeSpikeResult


def build_spike_markdown_header(total: int, sort_by=None) -> str:
    """表格上方條件說明＋排序方式。"""
    sort_desc = f" | 按{sort_by.display_name}排序" if sort_by else ""
    return f"共 {total} 檔 (≥1.5x){sort_desc}\n\n"


def build_spike_telegram_html_messages(
    results: list[VolumeSpikeResult],
    header: str,
    chunk: int = SPIKE_TABLE_CHUNK,
) -> list[str]:
    """
    與 build_spike_messages 相同分段邏輯，改為 HTML <pre> 包裝。
    """
    msgs: list[str] = []
    total_n = len(results)
    for i in range(0, total_n, chunk):
        part = results[i : i + chunk]
        if i == 0:
            plain = header
        else:
            plain = f"（續）第 {i + 1}-{i + len(part)} 筆\n\n"
        plain += get_table_header() + "".join(format_spike_row(r) for r in part) + "```\n"
        body = plain.replace("```", "").strip()
        msgs.append(f"<pre>{html.escape(body)}</pre>")
    return msgs
