"""Tests for bot/reply_docs.py."""

from bot.reply_docs import (
    build_html_document,
    build_markdown_document,
    safe_filename,
)


def test_build_html_wraps_body_in_full_document():
    """把 HTML 片段包成完整 HTML5 文件，含 CSS 樣式。"""
    doc = build_html_document("<h1>台積電</h1><p>內容</p>", title="台積電報告")
    assert doc.startswith("<!DOCTYPE html>")
    assert "<style>" in doc  # 內嵌 CSS
    assert "<h1>台積電</h1>" in doc  # 原始內文保留
    assert "<title>台積電報告</title>" in doc
    assert "prefers-color-scheme" in doc  # 深色模式


def test_build_html_default_title():
    """未給 title 時用預設。"""
    doc = build_html_document("<p>x</p>")
    assert "<title>台股分析報告</title>" in doc


def test_build_html_escapes_title():
    """title 的 HTML 特殊字元被跳脫，避免破壞 <title>。"""
    doc = build_html_document("<p>x</p>", title="a<b>&c")
    assert "<title>a&lt;b&gt;&amp;c</title>" in doc


def test_build_markdown_returns_content_with_trailing_newline():
    """Markdown 內文原樣、去首尾空白、補結尾換行。"""
    out = build_markdown_document("  # 標題\n\n內容  ")
    assert out == "# 標題\n\n內容\n"


def test_safe_filename_basic():
    md = safe_filename("台積電_2330_分析", "md")
    assert md == "台積電_2330_分析.md"


def test_safe_filename_strips_path_separators():
    """清掉路徑分隔字元，防目錄穿越。"""
    name = safe_filename("../../etc/passwd", "html")
    assert "/" not in name and "\\" not in name
    assert name.endswith(".html")


def test_safe_filename_spaces_to_underscore():
    assert safe_filename("台積電 分析 報告", "md") == "台積電_分析_報告.md"


def test_safe_filename_empty_falls_back():
    assert safe_filename("   ", "html") == "report.html"


def test_safe_filename_length_capped():
    name = safe_filename("超" * 200, "md")
    # 去掉 ".md" 後主體不超過 60。
    assert len(name) - len(".md") <= 60
