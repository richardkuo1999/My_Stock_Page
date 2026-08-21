"""tests for tools/fetch_threads.py"""

import asyncio
import json
import os
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tools.fetch_threads import (
    THREADS_API_BASE,
    _fetch_user_threads,
    _get_access_token,
    _load_config,
    check_new,
)


# --- Helpers ---

def _make_response(status_code: int, json_data: dict | None = None) -> httpx.Response:
    """Create a mock httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "https://example.com"),
    )
    return resp


SAMPLE_THREADS_RESPONSE = {
    "data": [
        {
            "id": "t_001",
            "text": "半導體利多消息",
            "timestamp": "2026-08-22T01:00:00+0000",
            "permalink": "https://www.threads.net/@user1/post/t_001",
        },
        {
            "id": "t_002",
            "text": "台積電法說會重點",
            "timestamp": "2026-08-21T10:00:00+0000",
            "permalink": "https://www.threads.net/@user1/post/t_002",
        },
    ]
}

SAMPLE_ME_RESPONSE = {"id": "12345", "username": "myuser"}


# --- Test _get_access_token ---

class TestGetAccessToken:
    def test_returns_token(self, monkeypatch):
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "test_token_123")
        assert _get_access_token() == "test_token_123"

    def test_returns_none_when_empty(self, monkeypatch):
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "")
        assert _get_access_token() is None

    def test_returns_none_when_missing(self, monkeypatch):
        monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
        assert _get_access_token() is None

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "  abc123  ")
        assert _get_access_token() == "abc123"


# --- Test _fetch_user_threads ---

class TestFetchUserThreads:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_resp = _make_response(200, SAMPLE_THREADS_RESPONSE)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.fetch_threads.httpx.AsyncClient", return_value=mock_client):
            posts = await _fetch_user_threads("user1", "token123")

        assert len(posts) == 2
        assert posts[0]["id"] == "t_001"
        assert posts[0]["user"] == "user1"
        assert posts[0]["text"] == "半導體利多消息"
        assert posts[0]["timestamp"] == "2026-08-22T01:00:00+0000"
        assert posts[0]["url"] == "https://www.threads.net/@user1/post/t_001"

    @pytest.mark.asyncio
    async def test_401_raises_permission_error(self):
        mock_resp = _make_response(401, {"error": {"message": "token expired"}})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.fetch_threads.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(PermissionError, match="token 已過期"):
                await _fetch_user_threads("user1", "expired_token")

    @pytest.mark.asyncio
    async def test_non_200_returns_empty(self):
        mock_resp = _make_response(500, {"error": "server error"})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.fetch_threads.httpx.AsyncClient", return_value=mock_client):
            posts = await _fetch_user_threads("user1", "token123")

        assert posts == []


# --- Test check_new ---

class TestCheckNew:
    @pytest.mark.asyncio
    async def test_no_token_returns_error(self, monkeypatch):
        monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
        result = await check_new()
        assert "error" in result
        assert "THREADS_ACCESS_TOKEN" in result["error"]

    @pytest.mark.asyncio
    async def test_success_with_configured_users(self, monkeypatch, tmp_path):
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "valid_token")

        config = {"threads_users": ["user_a"]}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        mock_resp = _make_response(200, SAMPLE_THREADS_RESPONSE)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.fetch_threads.CONFIG_PATH", config_file):
            with patch("tools.fetch_threads.httpx.AsyncClient", return_value=mock_client):
                result = await check_new()

        assert "posts" in result
        assert len(result["posts"]) == 2
        assert result["posts"][0]["user"] == "user_a"

    @pytest.mark.asyncio
    async def test_token_expired_returns_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "expired_token")

        config = {"threads_users": ["user_a"]}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        mock_resp = _make_response(401, {"error": {"message": "expired"}})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.fetch_threads.CONFIG_PATH", config_file):
            with patch("tools.fetch_threads.httpx.AsyncClient", return_value=mock_client):
                result = await check_new()

        assert "error" in result
        assert "過期" in result["error"]

    @pytest.mark.asyncio
    async def test_no_users_fallback_to_me(self, monkeypatch, tmp_path):
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "valid_token")

        config = {"threads_users": []}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        me_resp = _make_response(200, SAMPLE_ME_RESPONSE)
        threads_resp = _make_response(200, SAMPLE_THREADS_RESPONSE)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[me_resp, threads_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.fetch_threads.CONFIG_PATH", config_file):
            with patch("tools.fetch_threads.httpx.AsyncClient", return_value=mock_client):
                result = await check_new()

        assert "posts" in result
        assert len(result["posts"]) == 2
        assert result["posts"][0]["user"] == "12345"

    @pytest.mark.asyncio
    async def test_no_users_and_me_fails(self, monkeypatch, tmp_path):
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "valid_token")

        config = {"threads_users": []}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        me_resp = _make_response(401, None)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=me_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.fetch_threads.CONFIG_PATH", config_file):
            with patch("tools.fetch_threads.httpx.AsyncClient", return_value=mock_client):
                result = await check_new()

        assert "error" in result
        assert "未設定" in result["error"]

    @pytest.mark.asyncio
    async def test_multiple_users_aggregates(self, monkeypatch, tmp_path):
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "valid_token")

        config = {"threads_users": ["user_a", "user_b"]}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        resp_a = _make_response(200, {
            "data": [{"id": "a1", "text": "post A", "timestamp": "2026-08-22T02:00:00+0000", "permalink": "http://a1"}]
        })
        resp_b = _make_response(200, {
            "data": [{"id": "b1", "text": "post B", "timestamp": "2026-08-22T03:00:00+0000", "permalink": "http://b1"}]
        })

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resp_a, resp_b])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.fetch_threads.CONFIG_PATH", config_file):
            with patch("tools.fetch_threads.httpx.AsyncClient", return_value=mock_client):
                result = await check_new()

        assert "posts" in result
        assert len(result["posts"]) == 2
        # user_b has later timestamp, should be first
        assert result["posts"][0]["user"] == "user_b"
        assert result["posts"][1]["user"] == "user_a"

    @pytest.mark.asyncio
    async def test_partial_failure(self, monkeypatch, tmp_path):
        """One user fails (non-401), others succeed."""
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "valid_token")

        config = {"threads_users": ["user_a", "user_b"]}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        resp_a = _make_response(500, {"error": "server error"})
        resp_b = _make_response(200, {
            "data": [{"id": "b1", "text": "post B", "timestamp": "2026-08-22T03:00:00+0000", "permalink": "http://b1"}]
        })

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resp_a, resp_b])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.fetch_threads.CONFIG_PATH", config_file):
            with patch("tools.fetch_threads.httpx.AsyncClient", return_value=mock_client):
                result = await check_new()

        assert "posts" in result
        assert len(result["posts"]) == 1
        assert result["posts"][0]["user"] == "user_b"

    @pytest.mark.asyncio
    async def test_sorted_by_timestamp_desc(self, monkeypatch, tmp_path):
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "valid_token")

        config = {"threads_users": ["user_a"]}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        resp = _make_response(200, {
            "data": [
                {"id": "1", "text": "old", "timestamp": "2026-08-20T01:00:00+0000", "permalink": "http://1"},
                {"id": "2", "text": "mid", "timestamp": "2026-08-21T01:00:00+0000", "permalink": "http://2"},
                {"id": "3", "text": "new", "timestamp": "2026-08-22T01:00:00+0000", "permalink": "http://3"},
            ]
        })

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.fetch_threads.CONFIG_PATH", config_file):
            with patch("tools.fetch_threads.httpx.AsyncClient", return_value=mock_client):
                result = await check_new()

        assert result["posts"][0]["id"] == "3"
        assert result["posts"][1]["id"] == "2"
        assert result["posts"][2]["id"] == "1"


# --- Test CLI ---

class TestCLI:
    def test_cli_check_new_outputs_json(self):
        """Test that CLI --check-new outputs valid JSON (will error due to no real token)."""
        env = {**os.environ, "THREADS_ACCESS_TOKEN": ""}
        result = subprocess.run(
            [sys.executable, "-m", "tools.fetch_threads", "--check-new"],
            capture_output=True,
            text=True,
            env=env,
            cwd="/Users/richardkuo/Desktop/stock code/My_Stock_Page",
        )
        # Should exit 1 because no token set
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert "error" in output

    def test_cli_no_args_shows_error(self):
        """CLI with no --check-new shows usage error."""
        env = {**os.environ, "THREADS_ACCESS_TOKEN": ""}
        result = subprocess.run(
            [sys.executable, "-m", "tools.fetch_threads"],
            capture_output=True,
            text=True,
            env=env,
            cwd="/Users/richardkuo/Desktop/stock code/My_Stock_Page",
        )
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert "error" in output


# --- Test import ---

class TestImport:
    def test_import_check_new(self):
        """Verify from tools.fetch_threads import check_new works."""
        from tools.fetch_threads import check_new as imported_fn
        assert callable(imported_fn)
