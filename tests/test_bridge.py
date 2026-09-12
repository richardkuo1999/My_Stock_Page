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
                    "parameters": {"Command": "python tools/analysis/get_stock_price.py 2330"},
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
    assert "python tools/analysis/get_stock_price.py 2330" in res.tools[0].summary()
    assert res.tools_line().startswith("🔧 本次用了（1 次呼叫）：")


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


def test_toolcall_summary_shows_full_params():
    """ToolCall.summary() 完整顯示參數（不截斷），並挑純量值。"""
    tc = ToolCall(name="view_file", parameters={"AbsolutePath": "/a/b/c.py"})
    assert tc.summary() == "view_file(/a/b/c.py)"

    # 長參數不再截斷（原本會切成 37 字元 + "..."）
    long = ToolCall(name="edit", parameters={"content": "x" * 200})
    assert long.summary() == f"edit({'x' * 200})"

    assert ToolCall(name="lonely").summary() == "lonely"


def test_toolcall_summary_handles_commandline():
    """ToolCall.summary() extracts and cleans CommandLine/Command with priority."""
    # 移除 env 前綴，保留乾淨的指令
    tc_env = ToolCall(
        name="run_command",
        parameters={
            "CommandLine": '$env:PYTHONIOENCODING="utf-8"; python tools/raw/uanalyze.py 7873 --prompt 資料',
            "Cwd": "C:/some/path",
            "toolAction": "Running command",
        },
    )
    assert tc_env.summary() == "run_command(python tools/raw/uanalyze.py 7873 --prompt 資料)"

    # 長指令完整顯示、不截斷
    tc_long = ToolCall(
        name="run_command",
        parameters={
            "CommandLine": "python tools/raw/uanalyze.py 2330 --prompt 這是一段很長的中文提示內容用來測試截斷行為"
        },
    )
    expected_clean = "python tools/raw/uanalyze.py 2330 --prompt 這是一段很長的中文提示內容用來測試截斷行為"
    assert tc_long.summary() == f"run_command({expected_clean})"

    # 多行指令（python -c "..."）壓成單行，內容不遺漏
    tc_multiline = ToolCall(
        name="run_command",
        parameters={"Command": '.venv/bin/python -c "\nimport json\nprint(json)\n"'},
    )
    assert tc_multiline.summary() == 'run_command(.venv/bin/python -c " import json print(json) ")'

    # Command 參數作為後援
    tc_cmd = ToolCall(
        name="run_command",
        parameters={"Command": "python tools/analysis/get_stock_price.py 2330"},
    )
    assert tc_cmd.summary() == "run_command(python tools/analysis/get_stock_price.py 2330)"


def test_diff_quota_marks_consumption():
    """diff_quota() 標記本次消耗；差值 0（整數百分比未跨界）時不標記。"""
    from agent.bridge import diff_quota, format_quota_line

    before = [
        {"group": "Gemini", "window": "週", "remaining_pct": 98, "reset_at": ""},
        {"group": "Gemini", "window": "5 小時", "remaining_pct": 97, "reset_at": ""},
    ]
    after = [
        {"group": "Gemini", "window": "週", "remaining_pct": 96, "reset_at": ""},
        {"group": "Gemini", "window": "5 小時", "remaining_pct": 97, "reset_at": ""},
    ]
    merged = diff_quota(before, after)
    assert merged[0]["delta_pct"] == 2      # 98 → 96
    assert "delta_pct" not in merged[1]     # 沒變化就不標

    line = format_quota_line(merged)
    assert "週 4%／96%（本次 -2%" in line
    assert "5 小時 3%／97%" in line
    assert "本次" not in line.split("・")[1]  # 未變動的視窗不顯示本次


def test_format_quota_line_merges_delta_and_reset_into_one_paren():
    """本次消耗與重置時間同組括號（避免「（本次 -2%）（重置 04:52）」相連）。"""
    from agent.bridge import format_quota_line

    line = format_quota_line([{
        "group": "Gemini",
        "window": "5 小時",
        "remaining_pct": 95,
        "reset_at": "2026-09-12T20:52:45Z",
        "delta_pct": 2,
    }])
    assert "）（" not in line
    assert "本次 -2%・重置 " in line


def test_diff_quota_handles_missing_sides():
    """任一邊缺資料 / 對不上時不炸。"""
    from agent.bridge import diff_quota

    after = [{"group": "G", "window": "週", "remaining_pct": 50}]
    assert diff_quota([], after) == after
    assert diff_quota(after, []) == []
    # 群組對不上 → 原樣保留、不標 delta
    other = [{"group": "X", "window": "週", "remaining_pct": 90}]
    assert "delta_pct" not in diff_quota(other, after)[0]


def test_parse_usage_tsv_and_quota_line():
    """/usage 的 TSV 解析 + 額度區塊排版（用真實輸出格式）。"""
    from agent.bridge import _parse_usage_tsv, format_quota_line

    raw = (
        "Gemini Models\tWeekly Limit Remaining\t98%\t2026-09-18T14:17:59Z\n"
        "Gemini Models\tFive Hour Limit Remaining\t97%\t2026-09-12T20:52:45Z\n"
        "Claude and GPT models\tWeekly Limit Remaining\t81%\t2026-09-15T14:33:39Z\n"
    )
    limits = _parse_usage_tsv(raw)
    assert len(limits) == 3
    assert limits[0] == {
        "group": "Gemini",
        "window": "週",
        "remaining_pct": 98,
        "reset_at": "2026-09-18T14:17:59Z",
    }

    line = format_quota_line(limits)
    assert line.startswith("🎟️ 額度（已用／剩餘）")
    assert "Gemini：週 2%／98%" in line          # 已用 = 100 - 剩餘
    assert "5 小時 3%／97%" in line
    assert "Claude·GPT：週 19%／81%" in line


def test_parse_usage_tsv_tolerates_garbage_and_unknown_labels():
    """格式變動時不炸：非百分比行跳過、未知標籤保留原文。"""
    from agent.bridge import _parse_usage_tsv, format_quota_line

    assert _parse_usage_tsv("") == []
    assert _parse_usage_tsv("some error message\n") == []
    assert _parse_usage_tsv("A\tB\tnot-a-pct\tX\n") == []

    unknown = _parse_usage_tsv("New Model\tDaily Limit Remaining\t55%\n")
    assert unknown == [{
        "group": "New Model",
        "window": "Daily Limit Remaining",
        "remaining_pct": 55,
        "reset_at": "",
    }]
    assert "New Model：Daily Limit Remaining 45%／55%" in format_quota_line(unknown)
    assert format_quota_line([]) == ""


@pytest.mark.asyncio
async def test_fetch_usage_limits_returns_empty_when_agy_missing():
    """agy 不存在時額度查詢回 []，不丟例外（/ask 照常回覆）。"""
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        assert await AntigravityCLIBridge().fetch_usage_limits() == []


@pytest.mark.asyncio
async def test_fetch_usage_limits_parses_agy_output():
    """fetch_usage_limits() 解析 agy -p /usage 的 stdout。"""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(
        return_value=(b"Gemini Models\tWeekly Limit Remaining\t98%\t2026-09-18T14:17:59Z\n", b"")
    )
    mock_proc.returncode = 0
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as m:
        limits = await AntigravityCLIBridge().fetch_usage_limits()
    assert limits[0]["remaining_pct"] == 98
    assert "/usage" in m.call_args[0]          # 用 slash command 查


def test_agentresult_usage_line_shows_tokens_and_percent():
    """usage_line() 顯示 token 數與佔比（用真實 agy usage 欄位）。"""
    res = AgentResult(
        response="ok",
        usage={
            "input_tokens": 417499,
            "output_tokens": 25315,
            "thinking_tokens": 13661,
            "cache_read_tokens": 3638703,
            "total_tokens": 442814,
        },
    )
    line = res.usage_line()
    assert "📊 Token：442,814" in line          # 千分位
    assert "輸入 417,499・94.3%" in line        # 佔比
    assert "輸出 25,315・5.7%" in line
    assert "思考 13,661・3.1%" in line
    assert "快取讀 3,638,703（命中 89.7%）" in line


def test_agentresult_usage_line_empty_and_partial():
    """無 usage 回空；只有部分欄位時不炸、不顯示假 0。"""
    assert AgentResult(response="hi").usage_line() == ""
    assert AgentResult(response="hi", usage={}).usage_line() == ""
    # 只有 total（無明細、無 cache）
    only_total = AgentResult(response="hi", usage={"total_tokens": 1234}).usage_line()
    assert only_total == "📊 Token：1,234"
    # 有明細但 total 缺（不能除以 0）
    no_total = AgentResult(response="hi", usage={"input_tokens": 100}).usage_line()
    assert "輸入 100" in no_total and "%" not in no_total


def test_agentresult_tools_line_empty_without_tools():
    """tools_line() is empty when no tools were used."""
    assert AgentResult(response="hi").tools_line() == ""


def test_agentresult_tools_line_lists_every_call_in_full():
    """tools_line() 一筆一行、編號、附次數，且指令完整不截斷。"""
    long_cmd = ".venv/bin/python tools/raw/broker_reports.py --stock 2308 --limit 50 --sector 記憶體"
    res = AgentResult(
        response="ok",
        tools=[
            ToolCall(name="run_command", parameters={"Command": long_cmd}),
            ToolCall(name="view_file", parameters={"AbsolutePath": "/Users/x/.gemini/antigravity/config.json"}),
        ],
    )
    line = res.tools_line()
    assert line.startswith("🔧 本次用了（2 次呼叫）：")
    assert f"1. run_command({long_cmd})" in line          # 完整指令
    assert "2. view_file(/Users/x/.gemini/antigravity/config.json)" in line  # 完整路徑
    assert "..." not in line
    assert len(line.splitlines()) == 3                     # 標題 + 2 筆


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
