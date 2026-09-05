"""Tests for agent/bridge.py."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.bridge import AgentResult, AntigravityCLIBridge, ToolCall


@pytest.fixture
def bridge():
    """Create a bridge with short timeout for testing."""
    return AntigravityCLIBridge(timeout=5)


def _stream(*lines: dict) -> bytes:
    """Encode dicts as agy stream-json (one NDJSON event per line)."""
    return ("\n".join(json.dumps(x) for x in lines) + "\n").encode()


# A realistic stream-json transcript: init → tool (active/done) → result.
def _sample_stream(response: str = "台積電目前股價 580") -> bytes:
    return _stream(
        {"event": "x", "init": {}, "conversation_id": "c1"},
        {
            "event": "x",
            "step_update": {
                "step_type": "tool",
                "state": "ACTIVE",
                "tool_name": "run_command",
                "tool_info": {
                    "name": "run_command",
                    "parameters": {"Command": "python tools/get_stock_price.py 2330"},
                },
            },
        },
        {
            "event": "x",
            "step_update": {
                "step_type": "tool",
                "state": "DONE",
                "tool_name": "run_command",
                "tool_info": {"name": "run_command", "output": "..."},
            },
        },
        {
            "event": "x",
            "result": {
                "conversation_id": "c1",
                "status": "SUCCESS",
                "response": response,
                "usage": {"total_tokens": 100},
            },
        },
    )


@pytest.mark.asyncio
async def test_send_success(bridge):
    """send() returns the final response text parsed from stream-json."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(_sample_stream(), b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await bridge.send("台積電股價")

    assert result == "台積電目前股價 580"
    mock_proc.communicate.assert_called_once()


@pytest.mark.asyncio
async def test_send_detailed_collects_tools(bridge):
    """send_detailed() returns response plus the tools the Agent used."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(_sample_stream(), b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await bridge.send_detailed("台積電股價")

    assert isinstance(res, AgentResult)
    assert res.response == "台積電目前股價 580"
    assert res.status == "SUCCESS"
    assert res.conversation_id == "c1"
    assert res.usage == {"total_tokens": 100}
    # Only the ACTIVE tool event is recorded (not the DONE duplicate).
    assert [t.name for t in res.tools] == ["run_command"]
    assert "python tools/get_stock_price.py 2330" in res.tools[0].summary()
    assert res.tools_line().startswith("🔧 本次用了：")


@pytest.mark.asyncio
async def test_send_uses_stream_json_format(bridge):
    """send_detailed() invokes agy with --output-format stream-json."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(_sample_stream(), b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as m:
        await bridge.send_detailed("q")

    args = m.call_args[0]
    assert "--output-format" in args
    assert args[args.index("--output-format") + 1] == "stream-json"


@pytest.mark.asyncio
async def test_send_non_json_response(bridge):
    """send() falls back to raw stdout when output is not stream-json."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"plain text response", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await bridge.send("hello")

    assert result == "plain text response"


@pytest.mark.asyncio
async def test_send_skips_malformed_lines(bridge):
    """Malformed NDJSON lines are skipped, valid result still parsed."""
    raw = b"not json\n" + _sample_stream()
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(raw, b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await bridge.send_detailed("q")

    assert res.response == "台積電目前股價 580"
    assert [t.name for t in res.tools] == ["run_command"]


@pytest.mark.asyncio
async def test_send_timeout(bridge):
    """send() raises TimeoutError when process exceeds timeout."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.kill = MagicMock()
    mock_proc.returncode = -9

    call_count = 0

    async def fake_wait_for(coro, *, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            coro.close()
            raise asyncio.TimeoutError()
        return await coro

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("asyncio.wait_for", side_effect=fake_wait_for):
            with pytest.raises(TimeoutError, match="timed out"):
                await bridge.send("slow query")

    mock_proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_send_nonzero_exit(bridge):
    """send() raises RuntimeError on non-zero exit code."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"command not found"))
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="Agent error \\(code 1\\)"):
            await bridge.send("bad command")


@pytest.mark.asyncio
async def test_send_retries_once_then_succeeds(bridge):
    """暫時性失敗（exit 1）會自動重試一次；第二次成功則正常回覆。"""
    fail_proc = AsyncMock()
    fail_proc.communicate = AsyncMock(return_value=(b"", b"transient glitch"))
    fail_proc.returncode = 1

    ok_proc = AsyncMock()
    ok_proc.communicate = AsyncMock(return_value=(_sample_stream("重試後成功"), b""))
    ok_proc.returncode = 0

    with patch(
        "asyncio.create_subprocess_exec", side_effect=[fail_proc, ok_proc]
    ) as m:
        result = await bridge.send("台積電")

    assert result == "重試後成功"
    assert m.call_count == 2  # 首次失敗 + 重試一次


@pytest.mark.asyncio
async def test_send_error_detail_from_stdout(bridge):
    """agy 把錯誤寫在 stdout（stderr 空）時，錯誤訊息仍要抽得出來，非 Unknown。"""
    err_stream = _stream(
        {"event": "result", "result": {"status": "ERROR", "error": "工具執行逾時"}}
    )
    mock_proc = AsyncMock()
    # stderr 為空，錯誤只在 stdout —— 這正是 21:21 那次 "Unknown error" 的情境。
    mock_proc.communicate = AsyncMock(return_value=(err_stream, b""))
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="工具執行逾時"):
            await bridge.send("q")


@pytest.mark.asyncio
async def test_send_timeout_not_retried(bridge):
    """逾時不重試（重試只會再等一輪），直接拋 TimeoutError。"""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.kill = MagicMock()
    mock_proc.returncode = -9

    async def always_timeout(coro, *, timeout):
        coro.close()
        raise asyncio.TimeoutError()

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as m:
        with patch("asyncio.wait_for", side_effect=always_timeout):
            with pytest.raises(TimeoutError):
                await bridge.send("slow")

    assert m.call_count == 1  # 只跑一次，沒重試


def test_toolcall_summary_truncates_long_params():
    """ToolCall.summary() truncates over-long param values and picks scalars."""
    tc = ToolCall(name="view_file", parameters={"AbsolutePath": "/a/b/c.py"})
    assert tc.summary() == "view_file(/a/b/c.py)"

    long = ToolCall(name="edit", parameters={"content": "x" * 200})
    assert long.summary() == f"edit({'x' * 37}...)"

    assert ToolCall(name="lonely").summary() == "lonely"


def test_toolcall_summary_handles_commandline():
    """ToolCall.summary() extracts and cleans CommandLine/Command with priority."""
    # 移除 env 前綴，保留乾淨的指令
    tc_env = ToolCall(
        name="run_command",
        parameters={
            "CommandLine": '$env:PYTHONIOENCODING="utf-8"; python tools/uanalyze.py 7873 --prompt 資料',
            "Cwd": "C:/some/path",
            "toolAction": "Running command",
        },
    )
    assert tc_env.summary() == "run_command(python tools/uanalyze.py 7873 --prompt 資料)"

    # 指令超過 50 字元時截斷
    tc_long = ToolCall(
        name="run_command",
        parameters={
            "CommandLine": "python tools/uanalyze.py 2330 --prompt 這是一段很長的中文提示內容用來測試截斷行為"
        },
    )
    expected_clean = "python tools/uanalyze.py 2330 --prompt 這是一段很長的中文提示內容用來測試截斷行為"
    assert tc_long.summary() == f"run_command({expected_clean[:47]}...)"

    # Command 參數作為後援
    tc_cmd = ToolCall(
        name="run_command",
        parameters={"Command": "python tools/get_stock_price.py 2330"},
    )
    assert tc_cmd.summary() == "run_command(python tools/get_stock_price.py 2330)"


def test_agentresult_tools_line_empty_without_tools():
    """tools_line() is empty when no tools were used."""
    assert AgentResult(response="hi").tools_line() == ""


@pytest.mark.asyncio
async def test_is_available_true(bridge):
    """is_available() returns True when agy --version exits 0."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"agy 1.0.0", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await bridge.is_available()

    assert result is True


@pytest.mark.asyncio
async def test_is_available_false_not_found(bridge):
    """is_available() returns False when agy binary not found."""
    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("No such file"),
    ):
        result = await bridge.is_available()

    assert result is False


@pytest.mark.asyncio
async def test_is_available_false_timeout(bridge):
    """is_available() returns False when version check times out."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await bridge.is_available()

    assert result is False
