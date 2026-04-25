"""Tests for HTTP session helpers."""

import aiohttp
import pytest

from analysis_bot.services.http import close_session, create_session, get_session


@pytest.mark.asyncio
async def test_create_session_returns_client_session() -> None:
    session = create_session()
    assert isinstance(session, aiohttp.ClientSession)
    await session.close()


@pytest.mark.asyncio
async def test_create_session_uses_certifi_ssl() -> None:
    session = create_session()
    connector = session.connector
    assert connector is not None
    assert connector._ssl is not None
    await session.close()


@pytest.mark.asyncio
async def test_create_session_passes_kwargs() -> None:
    timeout = aiohttp.ClientTimeout(total=5)
    session = create_session(timeout=timeout)
    assert session.timeout.total == 5
    await session.close()


@pytest.mark.asyncio
async def test_get_session_returns_singleton() -> None:
    s1 = get_session()
    s2 = get_session()
    assert s1 is s2
    await close_session()


@pytest.mark.asyncio
async def test_close_session_cleans_up() -> None:
    s = get_session()
    assert not s.closed
    await close_session()
    # After close, get_session should create a new one
    s2 = get_session()
    assert s2 is not s
    await close_session()
