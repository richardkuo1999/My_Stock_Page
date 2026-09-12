"""Tests for tools/analysis/_chart_font.py（跨平台中文字型設定）。"""

from types import SimpleNamespace
from unittest.mock import patch

import matplotlib

from tools.analysis._chart_font import setup_cjk_font


def _fake_font_list(names):
    # font_manager 的 entry 只需 .name 屬性；SimpleNamespace 避開 MagicMock 的 name 保留字。
    return [SimpleNamespace(name=n) for n in names]


def test_setup_picks_available_cjk_font():
    """有可用 CJK 字型時，設為 sans-serif 首選並回傳其名。"""
    fake = _fake_font_list(["DejaVu Sans", "Microsoft JhengHei", "Arial"])
    with patch("matplotlib.font_manager.fontManager") as fm:
        fm.ttflist = fake
        chosen = setup_cjk_font()
    assert chosen == "Microsoft JhengHei"
    assert matplotlib.rcParams["font.sans-serif"][0] == "Microsoft JhengHei"
    assert matplotlib.rcParams["axes.unicode_minus"] is False


def test_setup_prefers_higher_priority():
    """多個可用時，依優先序（正體 > 簡體 > 通用）選最前面的。"""
    fake = _fake_font_list(["Arial Unicode MS", "PingFang TC", "SimHei"])
    with patch("matplotlib.font_manager.fontManager") as fm:
        fm.ttflist = fake
        chosen = setup_cjk_font()
    assert chosen == "PingFang TC"


def test_setup_no_cjk_font_returns_none():
    """完全無 CJK 字型時回 None，不拋例外。"""
    fake = _fake_font_list(["DejaVu Sans", "Arial"])
    with patch("matplotlib.font_manager.fontManager") as fm:
        fm.ttflist = fake
        chosen = setup_cjk_font()
    assert chosen is None
