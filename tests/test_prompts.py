"""Tests for agent/prompts.py."""

from agent.prompts import SYSTEM_PROMPT, build_mention_prompt


def test_system_prompt_describes_role():
    """System prompt identifies the assistant as a Taiwan-stock helper."""
    assert "台股" in SYSTEM_PROMPT
    assert "繁體中文" in SYSTEM_PROMPT


def test_system_prompt_points_to_tools_readme():
    """System prompt tells the Agent to read tools/README.md for the tool catalog.

    工具清單的真實來源改為 tools/README.md（避免 prompt 內清單過時），
    prompt 只需指引 Agent 去讀它 + 讀各檔 docstring 拿細節。
    """
    assert "tools/README.md" in SYSTEM_PROMPT
    # 指引讀 README 與各檔 docstring
    assert "cat tools/README.md" in SYSTEM_PROMPT
    assert "docstring" in SYSTEM_PROMPT


def test_system_prompt_describes_format_choice():
    """Prompt 說明 Agent 可用 FORMAT 標記自選 text / html / markdown。"""
    assert "FORMAT: html" in SYSTEM_PROMPT
    assert "FORMAT: text" in SYSTEM_PROMPT
    assert "FORMAT: markdown" in SYSTEM_PROMPT
    # html/markdown 是「送檔案附件」而非 Telegram 訊息內嵌。
    assert ".html 檔案" in SYSTEM_PROMPT
    assert ".md 檔案" in SYSTEM_PROMPT


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
