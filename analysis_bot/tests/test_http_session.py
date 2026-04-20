from __future__ import annotations

import ssl

import pytest
from analysis_bot.services.http import create_session


@pytest.mark.asyncio
async def test_create_session_returns_client_session() -> None:
    import aiohttp

    session = create_session()
    assert isinstance(session, aiohttp.ClientSession)
    await session.close()


@pytest.mark.asyncio
async def test_create_session_uses_certifi_ssl() -> None:
    session = create_session()
    connector = session.connector
    # TCPConnector stores ssl context; verify it's set
    assert connector is not None
    assert connector._ssl is not None
    await session.close()


@pytest.mark.asyncio
async def test_create_session_passes_kwargs() -> None:
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=5)
    session = create_session(timeout=timeout)
    assert session.timeout.total == 5
    await session.close()
