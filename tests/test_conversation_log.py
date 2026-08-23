"""Tests for agent/conversation_log.py."""

import json

from agent.bridge import AgentResult, ToolCall
from agent.conversation_log import log_conversation


def test_log_conversation_writes_jsonl(tmp_path):
    """log_conversation appends a well-formed JSON line with all fields."""
    path = tmp_path / "conv.jsonl"
    result = AgentResult(
        response="台積電 2410",
        tools=[
            ToolCall(name="run_command", parameters={"Command": "python x.py 2330"})
        ],
        status="SUCCESS",
        conversation_id="abc",
        usage={"total_tokens": 42},
    )

    log_conversation(
        question="台積電股價",
        result=result,
        user_id=123,
        chat_id=456,
        path=path,
    )

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["question"] == "台積電股價"
    assert rec["response"] == "台積電 2410"
    assert rec["user_id"] == 123
    assert rec["chat_id"] == 456
    assert rec["status"] == "SUCCESS"
    assert rec["conversation_id"] == "abc"
    assert rec["usage"] == {"total_tokens": 42}
    assert rec["tools"] == [
        {"name": "run_command", "parameters": {"Command": "python x.py 2330"}}
    ]
    assert "timestamp" in rec


def test_log_conversation_appends(tmp_path):
    """Multiple calls append rather than overwrite."""
    path = tmp_path / "conv.jsonl"
    for i in range(3):
        log_conversation(
            question=f"q{i}", result=AgentResult(response=f"a{i}"), path=path
        )
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[2])["question"] == "q2"


def test_log_conversation_never_raises(tmp_path):
    """A write failure must be swallowed, not propagated to the caller."""
    # Point at a path whose parent is a file → mkdir/open will fail.
    bad_parent = tmp_path / "afile"
    bad_parent.write_text("x")
    path = bad_parent / "conv.jsonl"

    # Should not raise despite the invalid path.
    log_conversation(question="q", result=AgentResult(response="a"), path=path)
