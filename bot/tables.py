"""Monospace text-table helpers (presentation layer only).

Telegram does not render Markdown tables, but it does render fenced ```code
blocks``` in a monospace font. The most portable way to show multi-dimensional
data (財務指標近 5 年 × 多指標、法人共識多期…) on a phone is therefore a
**space-aligned text table wrapped in a code fence**.

The tricky part is alignment: CJK characters (中文) render roughly twice as wide
as ASCII in a monospace font, so naive `str.ljust` misaligns columns. These
helpers pad by *display width* (`unicodedata.east_asian_width`), not character
count.

Architecture note: this module is pure presentation. Tools still return plain
summary JSON; only bot handlers (and, by prompt instruction, the Agent) turn
that JSON into tables. No AI, no network, no tool contract changes.
"""

from __future__ import annotations

import unicodedata
from typing import Iterable, Sequence

__all__ = ["display_width", "pad", "render_table", "code_block", "code_block_capped"]

# Telegram rejects any single message longer than this many characters.
TELEGRAM_MAX_CHARS = 4096


def display_width(text: str) -> int:
    """Return the monospace display width of *text*.

    East-Asian "Wide" (W) and "Fullwidth" (F) characters count as 2 columns;
    everything else counts as 1. This matches how a fixed-width font lays out
    mixed CJK/ASCII text in a Telegram code block.
    """
    width = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def pad(text: str, width: int, align: str = "left") -> str:
    """Pad *text* with spaces to *width* display columns.

    align: "left" | "right" | "center". If the text is already at least
    *width* columns wide, it is returned unchanged.
    """
    gap = width - display_width(text)
    if gap <= 0:
        return text
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def render_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    aligns: Sequence[str] | None = None,
    sep: str = "  ",
) -> str:
    """Render *headers* + *rows* as a space-aligned monospace text table.

    Args:
        headers: column header cells.
        rows: iterable of rows; each row is a sequence of cell values (any type,
            stringified via str()). Rows may be shorter/longer than headers;
            short rows are padded with empty cells, extra cells are dropped.
        aligns: optional per-column alignment ("left"/"right"/"center").
            Defaults to left for the first column and right for the rest
            (labels left, numbers right — the common financial layout).
        sep: column separator string.

    Returns:
        The table as a plain multi-line string (no code fence). Empty rows with
        no headers → empty string.
    """
    header_cells = [str(h) for h in headers]
    ncols = len(header_cells)

    norm_rows: list[list[str]] = []
    for row in rows:
        cells = [str(c) for c in row]
        if len(cells) < ncols:
            cells += [""] * (ncols - len(cells))
        elif len(cells) > ncols:
            cells = cells[:ncols]
        norm_rows.append(cells)

    if ncols == 0:
        return ""

    if aligns is None:
        aligns = ["left"] + ["right"] * (ncols - 1)
    else:
        aligns = list(aligns)
        if len(aligns) < ncols:
            aligns += ["left"] * (ncols - len(aligns))

    # Column widths = max display width across header + all rows.
    widths = [display_width(header_cells[i]) for i in range(ncols)]
    for cells in norm_rows:
        for i in range(ncols):
            w = display_width(cells[i])
            if w > widths[i]:
                widths[i] = w

    def fmt_row(cells: Sequence[str]) -> str:
        return sep.join(
            pad(cells[i], widths[i], aligns[i]) for i in range(ncols)
        ).rstrip()

    lines = [fmt_row(header_cells)]
    # Divider line sized to the total table width.
    divider_width = sum(widths) + len(sep) * (ncols - 1)
    lines.append("-" * divider_width)
    for cells in norm_rows:
        lines.append(fmt_row(cells))
    return "\n".join(lines)


def code_block(text: str) -> str:
    """Wrap *text* in a Telegram-compatible fenced code block.

    Use with `parse_mode="Markdown"` (legacy). Inside a fence, only backticks
    are special, so arbitrary CJK/number content is safe. Any literal triple
    backticks in *text* are defanged to avoid breaking out of the fence.
    """
    safe = text.replace("```", "``\u200b`")
    return f"```\n{safe}\n```"


def code_block_capped(body: str, limit: int = TELEGRAM_MAX_CHARS) -> str:
    """Fence *body* in a code block whose *final* length is <= *limit*.

    Wrapping is done first, then the result is measured — so the fence markers
    and any inside-fence escaping (```` ``` ```` → ``` ``\u200b` ````, which grows
    the string) are always counted. This avoids the off-by error of budgeting a
    fixed number of characters for the fence before wrapping.

    If the fenced body is too long, *body* is truncated (by character) and
    re-fenced until it fits. An ellipsis marks the cut.
    """
    wrapped = code_block(body)
    if len(wrapped) <= limit:
        return wrapped

    ellipsis = "…"
    # Binary-search-free shrink: repeatedly trim the body proportionally to the
    # overshoot, re-wrap, and recheck. Converges in a couple of iterations
    # because escaping only ever *adds* characters (monotonic).
    trimmed = body
    while trimmed:
        overshoot = len(code_block(trimmed + ellipsis)) - limit
        if overshoot <= 0:
            return code_block(trimmed + ellipsis)
        # Trim at least the overshoot; strip whole chars from the end.
        cut = max(1, overshoot)
        trimmed = trimmed[:-cut]
    # Body trimmed away entirely — return an empty (but valid) fence.
    return code_block("")

