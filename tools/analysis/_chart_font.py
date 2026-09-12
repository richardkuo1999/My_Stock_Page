"""_chart_font — 跨平台中文字型設定（給 analysis 的繪圖工具共用）。

matplotlib 預設字型無中文字，圖上中文會變方框。這裡從各平台常見的 CJK 字型
（macOS / Windows / Linux）挑一個 matplotlib 實際看得到的設為 sans-serif 首選，
並修正負號顯示。找不到任何 CJK 字型時安靜略過（英文/數字仍正常）。

用法：繪圖模組 import 後呼叫一次 `setup_cjk_font()`（冪等）。
"""

import logging

logger = logging.getLogger(__name__)

# 優先序：台灣正體 → 簡體 → 通用 Unicode。涵蓋 macOS / Windows / Linux。
_CJK_CANDIDATES = [
    "PingFang TC",          # macOS
    "Heiti TC",             # macOS
    "Hiragino Sans GB",     # macOS
    "Microsoft JhengHei",   # Windows 正體
    "Microsoft YaHei",      # Windows 簡體
    "SimHei",               # Windows 後援
    "Noto Sans CJK TC",     # Linux
    "Noto Sans CJK SC",     # Linux
    "STHeiti",              # macOS 後援
    "Arial Unicode MS",     # 通用後援
]

_done = False


def setup_cjk_font() -> str | None:
    """設定 matplotlib 中文字型（冪等）。回傳選中的字型名，或 None（無可用）。"""
    global _done
    import matplotlib
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((f for f in _CJK_CANDIDATES if f in available), None)
    if chosen:
        # 放在既有 sans-serif 清單最前面，其餘保留當後援。
        existing = [f for f in matplotlib.rcParams.get("font.sans-serif", []) if f != chosen]
        matplotlib.rcParams["font.sans-serif"] = [chosen] + existing
        matplotlib.rcParams["axes.unicode_minus"] = False  # 負號正常顯示
    elif not _done:
        logger.debug("找不到可用中文字型，圖上中文可能顯示為方框")
    _done = True
    return chosen
