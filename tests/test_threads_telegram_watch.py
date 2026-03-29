"""threads_telegram_watch 純邏輯單元測試（不依賴 Playwright / Telegram API）。"""

import json
from pathlib import Path

import pytest

from analysis_bot.services.threads_watch_service import (
    ThreadPost,
    load_state,
    merge_seen_json,
    pick_new_posts,
    sanitize_telegram_text,
    save_state,
    trim_threads_ui_prefix,
)


def test_pick_new_posts_order():
    posts = [
        ThreadPost("a", "https://x/a", "ta"),
        ThreadPost("b", "https://x/b", "tb"),
    ]
    assert pick_new_posts(posts, set()) == posts
    assert pick_new_posts(posts, {"a"}) == [posts[1]]
    assert pick_new_posts(posts, {"a", "b"}) == []


def test_trim_threads_ui_prefix():
    raw = "klu_jfk\n5天\n\n我不是詐騙。\n翻譯"
    assert "我不是詐騙" in trim_threads_ui_prefix(raw)
    assert "klu_jfk" not in trim_threads_ui_prefix(raw)


def test_sanitize_telegram_text_strips_control_chars():
    s = "hello\x00world"
    assert sanitize_telegram_text(s, 100) == "helloworld"


def test_sanitize_telegram_text_truncates():
    long = "x" * 100
    out = sanitize_telegram_text(long, 50)
    assert len(out) < len(long)
    assert "截斷" in out


def test_load_save_state_roundtrip(tmp_path: Path):
    p = tmp_path / "st.json"
    save_state(p, {"seen_ids": ["p1", "p2"], "version": 1})
    data = load_state(p)
    assert data["seen_ids"] == ["p1", "p2"]
    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_state(corrupt)["seen_ids"] == []


def test_merge_seen_json():
    s = merge_seen_json('["a"]', ["b", "a"])
    data = json.loads(s)
    assert "b" in data and "a" in data


def test_save_state_caps_seen_ids(tmp_path: Path):
    p = tmp_path / "cap.json"
    many = [f"id{i}" for i in range(900)]
    save_state(p, {"seen_ids": many})
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data["seen_ids"]) == 800
