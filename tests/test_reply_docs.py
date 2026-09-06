"""Tests for bot/reply_docs.py."""

from bot.reply_docs import (
    build_html_document,
    build_markdown_document,
    safe_filename,
    title_from_body,
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


def test_title_from_body_html_h1():
    """HTML 內文取第一個 <h1> 當標題。"""
    body = "<h1>金像電 (2368) 投資研究報告</h1>\n<p>x</p>"
    assert title_from_body(body, "html") == "金像電 (2368) 投資研究報告"


def test_title_from_body_html_strips_inner_tags_and_entities():
    """<h1> 內含子標籤與 HTML 實體時，清成純文字。"""
    body = "<h1>台積電 <b>2330</b> &amp; 報告</h1>"
    assert title_from_body(body, "html") == "台積電 2330 & 報告"


def test_title_from_body_markdown_heading():
    """Markdown 取第一個 # 標題行。"""
    body = "# 聯發科 2454 深度分析\n\n內容"
    assert title_from_body(body, "markdown") == "聯發科 2454 深度分析"


def test_title_from_body_markdown_h2_when_no_h1():
    """Markdown 沒有 # 只有 ## 時也能取到。"""
    body = "## 產業近況\n內容"
    assert title_from_body(body, "markdown") == "產業近況"


def test_title_from_body_no_title_returns_empty():
    """找不到標題回空字串（交由呼叫端後援）。"""
    assert title_from_body("<p>沒有標題</p>", "html") == ""
    assert title_from_body("純文字沒有標題", "markdown") == ""


def test_title_from_body_empty():
    assert title_from_body("", "html") == ""


def test_title_from_body_feeds_safe_filename():
    """標題經 safe_filename 後成為合法檔名（空白轉底線）。"""
    title = title_from_body("<h1>金像電 2368 報告</h1>", "html")
    assert safe_filename(title, "html") == "金像電_2368_報告.html"
