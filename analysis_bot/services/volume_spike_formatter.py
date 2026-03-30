"""
VolumeSpikeFormatter — 爆量偵測結果的格式化輸出。
供 handlers、scheduler、run_volume_spike 共用。
中／英欄寬以「顯示寬度」對齊（CJK 佔 2），避免 Telegram 等寬字體跑版。
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .volume_spike_scanner import VolumeSpikeResult

SPIKE_TABLE_CHUNK = 80

# 欄位顯示寬度（等寬字體下 CJK=2、ASCII=1）
TICKER_W = 6
# 名稱略窄，視覺上與下一欄較近
NAME_W = 8
# 股價與漲跌幅合併為「股價(漲幅)」一欄，例如 600.0 (+1.5%)
PRICE_CHG_W = 18
# 「 1234.5x」欄寬；與上一欄之間僅 1 空白
RATIO_FIELD_W = 8

# 第一上市櫃等後綴；截斷時須整段保留，避免「-K」後僅剩 1 寬度而吃掉尾端 y
_STOCK_NAME_SUFFIXES: tuple[str, ...] = ("-KY", "-DR")


def _char_display_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1


def display_width(s: str) -> int:
    """字串在等寬字體下的顯示寬度（概估）。"""
    return sum(_char_display_width(c) for c in s)


def _fit_visual_width(s: str, max_w: int) -> str:
    out: list[str] = []
    w = 0
    for ch in s:
        cw = _char_display_width(ch)
        if w + cw > max_w:
            break
        out.append(ch)
        w += cw
    return "".join(out)


def pad_visual(s: str, width: int) -> str:
    """以空白右補至固定顯示寬度；過長則截斷。"""
    fitted = _fit_visual_width(s, width)
    return fitted + " " * (width - display_width(fitted))


def _fit_stock_name(name: str, max_w: int) -> str:
    """
    依顯示寬度截斷名稱；若結尾為 -KY / -DR 等，優先保留完整後綴再截前面。
    避免固定欄寬剛好落在「-K」與「y」之間時只顯示 -K。
    """
    if display_width(name) <= max_w:
        return name
    n = name.rstrip()
    for suf in _STOCK_NAME_SUFFIXES:
        if len(n) < len(suf) or not n.upper().endswith(suf.upper()):
            continue
        actual_suf = n[-len(suf) :]
        su_w = display_width(actual_suf)
        if su_w > max_w:
            return _fit_visual_width(name, max_w)
        prefix = n[: -len(suf)]
        pw = max_w - su_w
        if pw <= 0:
            return _fit_visual_width(actual_suf, max_w)
        fitted_prefix = _fit_visual_width(prefix, pw)
        return fitted_prefix + actual_suf
    return _fit_visual_width(name, max_w)


def pad_stock_name(name: str, width: int = NAME_W) -> str:
    """名稱欄：截斷規則見 _fit_stock_name。"""
    fitted = _fit_stock_name(name, width)
    return fitted + " " * (width - display_width(fitted))


def pad_price_chg_cell(
    r: VolumeSpikeResult,
    width: int | None = None,
) -> str:
    """股價與漲跌幅合併，右對齊於固定顯示寬度。"""
    w = PRICE_CHG_W if width is None else width
    if r.change_pct is None:
        inner = f"{r.close:.1f} (--)"
    else:
        inner = f"{r.close:.1f} ({r.change_pct:+.1f}%)"
    dw = display_width(inner)
    if dw < w:
        return " " * (w - dw) + inner
    return _fit_visual_width(inner, w)


def format_spike_row(r: VolumeSpikeResult) -> str:
    """單筆爆量股的表格列。"""
    ratio_s = f"{r.spike_ratio:>6.1f}x".rjust(RATIO_FIELD_W)
    return (
        f"{pad_visual(str(r.ticker), TICKER_W)}"
        f"{pad_stock_name(r.name)}"
        f"{pad_price_chg_cell(r)}"
        f" {ratio_s}\n"
    )


def get_table_header() -> str:
    """表格標題列與分隔線。"""
    line = (
        f"{pad_visual('代碼', TICKER_W)}"
        f"{pad_visual('名稱', NAME_W)}"
        f"{pad_visual('股價(漲幅)', PRICE_CHG_W)}"
        f" {pad_visual('倍數', RATIO_FIELD_W)}\n"
    )
    dash_len = TICKER_W + NAME_W + PRICE_CHG_W + 1 + RATIO_FIELD_W
    return f"```\n{line}{'-' * dash_len}\n"


def build_spike_messages(
    results: list[VolumeSpikeResult],
    header: str,
    chunk: int = SPIKE_TABLE_CHUNK,
) -> list[str]:
    """
    將爆量結果切成多則訊息（每則約 chunk 筆）。
    回傳訊息列表，每則含 header（首則）或續集標題 + 表格。
    """
    msgs = []
    for i in range(0, len(results), chunk):
        part = results[i : i + chunk]
        if i == 0:
            msg = header
        else:
            msg = f"（續）第 {i + 1}-{i + len(part)} 筆\n\n"
        msg += get_table_header() + "".join(format_spike_row(r) for r in part) + "```\n"
        msgs.append(msg)
    return msgs
