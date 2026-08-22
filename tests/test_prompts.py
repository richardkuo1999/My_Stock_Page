"""Tests for agent/prompts.py."""

from agent.prompts import SYSTEM_PROMPT, build_mention_prompt


def test_system_prompt_describes_role():
    """System prompt identifies the assistant as a Taiwan-stock helper."""
    assert "台股" in SYSTEM_PROMPT
    assert "繁體中文" in SYSTEM_PROMPT


def test_system_prompt_lists_all_tools():
    """System prompt references every tool script so the Agent knows they exist."""
    for tool in (
        "get_stock_price.py",
        "draw_kchart.py",
        "fetch_news.py",
        "uanalyze.py",
        "fetch_threads.py",
        "summarize_document.py",
    ):
        assert tool in SYSTEM_PROMPT


def test_build_mention_prompt_includes_question_and_system():
    """The full prompt contains both the system prompt and the user's question."""
    prompt = build_mention_prompt("台積電現在多少錢？")
    assert "台積電現在多少錢？" in prompt
    assert SYSTEM_PROMPT in prompt


def test_build_mention_prompt_strips_whitespace():
    """User question is stripped of surrounding whitespace."""
    prompt = build_mention_prompt("  2330 新聞  ")
    assert "2330 新聞" in prompt
    assert "  2330 新聞  " not in prompt
