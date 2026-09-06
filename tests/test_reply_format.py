"""Tests for bot/reply_format.py."""

from bot.reply_format import parse_reply_format


def test_no_marker_defaults_to_text():
    """缺標記時視為純文字，內容原樣不動。"""
    mode, body = parse_reply_format("台積電今天收盤 1000 元")
    assert mode == "text"
    assert body == "台積電今天收盤 1000 元"


def test_html_marker_parsed_and_stripped():
    """FORMAT: html 被辨識，標記行被切掉。"""
    mode, body = parse_reply_format("FORMAT: html\n<b>台積電</b> 1000 元")
    assert mode == "html"
    assert body == "<b>台積電</b> 1000 元"


def test_text_marker_parsed_and_stripped():
    """FORMAT: text 被辨識，標記行被切掉。"""
    mode, body = parse_reply_format("FORMAT: text\n台積電 1000 元")
    assert mode == "text"
    assert body == "台積電 1000 元"


def test_markdown_marker_parsed_and_stripped():
    """FORMAT: markdown 被辨識，標記行被切掉。"""
    mode, body = parse_reply_format("FORMAT: markdown\n# 台積電\n內容")
    assert mode == "markdown"
    assert body == "# 台積電\n內容"


def test_marker_case_insensitive():
    """標記大小寫不拘。"""
    mode, body = parse_reply_format("format: HTML\n<b>x</b>")
    assert mode == "html"
    assert body == "<b>x</b>"


def test_marker_tolerates_fullwidth_colon_and_spaces():
    """容忍全形冒號與前後空白。"""
    mode, body = parse_reply_format("  FORMAT ： html \n內容")
    assert mode == "html"
    assert body == "內容"


def test_unrecognized_format_value_falls_back_to_text():
    """FORMAT 後接非 html/text/markdown → 不視為標記，整段當純文字。"""
    mode, body = parse_reply_format("FORMAT: pdf\n# 標題")
    assert mode == "text"
    assert body == "FORMAT: pdf\n# 標題"


def test_format_word_mid_text_is_not_a_marker():
    """只認第一行的標記；內文出現 FORMAT 字樣不算。"""
    mode, body = parse_reply_format("台積電\nFORMAT: html")
    assert mode == "text"
    assert body == "台積電\nFORMAT: html"


def test_empty_reply():
    """空字串安全處理。"""
    mode, body = parse_reply_format("")
    assert mode == "text"
    assert body == ""


def test_html_marker_only_no_body():
    """只有標記行、沒有正文。"""
    mode, body = parse_reply_format("FORMAT: html")
    assert mode == "html"
    assert body == ""


def test_leading_blank_lines_before_marker():
    """標記前有空白行仍能辨識（LLM 常見雜訊）。"""
    mode, body = parse_reply_format("\n\nFORMAT: html\n<h1>hi</h1>")
    assert mode == "html"
    assert body == "<h1>hi</h1>"


def test_code_fence_wrapped_reply():
    """整段回覆被 ``` code fence 包住，仍能辨識並去除包裹。"""
    reply = "```\nFORMAT: html\n<h1>hi</h1>\n```"
    mode, body = parse_reply_format(reply)
    assert mode == "html"
    assert body == "<h1>hi</h1>"


def test_code_fence_with_language_tag():
    """開頭 fence 帶語言名（```html）也能辨識。"""
    reply = "```html\nFORMAT: html\n<h1>hi</h1>\n```"
    mode, body = parse_reply_format(reply)
    assert mode == "html"
    assert body == "<h1>hi</h1>"


def test_tilde_fence_wrapped_reply():
    """~~~ 形式的 fence 同樣支援。"""
    reply = "~~~\nFORMAT: markdown\n# hi\n~~~"
    mode, body = parse_reply_format(reply)
    assert mode == "markdown"
    assert body == "# hi"


def test_prose_before_marker_still_text():
    """標記前有實質文字（非空白、非 fence）→ 仍視為純文字，不誤判。"""
    reply = "好的，以下是報告：\nFORMAT: html\n<h1>hi</h1>"
    mode, body = parse_reply_format(reply)
    assert mode == "text"
    assert body == reply


def test_fence_wrap_multiline_html_body_preserved():
    """fence 包住的多行 HTML，內文換行需保留、只切掉包裹 fence。"""
    reply = "```\nFORMAT: html\n<h1>標題</h1>\n<p>段落</p>\n```"
    mode, body = parse_reply_format(reply)
    assert mode == "html"
    assert body == "<h1>標題</h1>\n<p>段落</p>"
