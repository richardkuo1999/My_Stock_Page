"""Shared aiohttp helpers with proper SSL configuration."""

import ssl

import aiohttp
import certifi

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def create_session(**kwargs) -> aiohttp.ClientSession:
    """Create an aiohttp.ClientSession with certifi SSL context."""
    connector = kwargs.pop("connector", None)
    if connector is None:
        connector = aiohttp.TCPConnector(ssl=_SSL_CTX)
    return aiohttp.ClientSession(connector=connector, **kwargs)
