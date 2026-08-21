"""Tests for agent/bridge.py."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.bridge import AntigravityCLIBridge


@pytest.fixture
def bridge():
    """Create a bridge with short timeout for testing."""
    return AntigravityCLIBridge(timeout=5)


@pytest.mark.asyncio
async def test_send_success(bridge):
    """send() returns parsed response field from JSON output."""
    response_data = json.dumps({"response": "台積電目前股價 580"}).encode()

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(response_data, b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await bridge.send("台積電股價")

    assert result == "台積電目前股價 580"
    mock_proc.communicate.assert_called_once()


@pytest.mark.asyncio
async def test_send_non_json_response(bridge):
    """send() returns raw stdout when output is not JSON."""
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"plain text response", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await bridge.send("hello")

    assert result == "plain text response"


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
            # Close the coroutine to avoid RuntimeWarning
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
