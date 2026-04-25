"""Tests for http_retry: retries on 5xx/network errors, skips 4xx."""

import aiohttp
import pytest

from analysis_bot.services.http import _is_retryable, http_retry


def test_is_retryable_5xx():
    exc = aiohttp.ClientResponseError(None, None, status=502, message="Bad Gateway")
    assert _is_retryable(exc) is True


def test_is_retryable_4xx():
    exc = aiohttp.ClientResponseError(None, None, status=404, message="Not Found")
    assert _is_retryable(exc) is False


def test_is_retryable_403():
    exc = aiohttp.ClientResponseError(None, None, status=403, message="Forbidden")
    assert _is_retryable(exc) is False


def test_is_retryable_network_error():
    assert _is_retryable(aiohttp.ClientConnectionError("conn reset")) is True


def test_is_retryable_timeout():
    assert _is_retryable(TimeoutError()) is True


def test_is_retryable_os_error():
    assert _is_retryable(OSError("DNS failed")) is True


def test_is_retryable_value_error():
    assert _is_retryable(ValueError("bad data")) is False


@pytest.mark.asyncio
async def test_http_retry_retries_on_5xx():
    call_count = 0

    @http_retry
    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise aiohttp.ClientResponseError(None, None, status=503, message="Unavailable")
        return "ok"

    result = await flaky()
    assert result == "ok"
    assert call_count == 3


@pytest.mark.asyncio
async def test_http_retry_no_retry_on_4xx():
    call_count = 0

    @http_retry
    async def not_found():
        nonlocal call_count
        call_count += 1
        raise aiohttp.ClientResponseError(None, None, status=404, message="Not Found")

    with pytest.raises(aiohttp.ClientResponseError):
        await not_found()
    assert call_count == 1  # no retry
