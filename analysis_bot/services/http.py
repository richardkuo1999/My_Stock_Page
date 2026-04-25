"""Shared aiohttp helpers with proper SSL configuration."""

import ssl

import aiohttp
import certifi
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def create_session(**kwargs) -> aiohttp.ClientSession:
    """Create an aiohttp.ClientSession with certifi SSL context."""
    connector = kwargs.pop("connector", None)
    if connector is None:
        connector = aiohttp.TCPConnector(ssl=_SSL_CTX)
    return aiohttp.ClientSession(connector=connector, **kwargs)


def _is_retryable(exc: BaseException) -> bool:
    """Return True for errors worth retrying (network errors, 5xx). Skip 4xx."""
    if isinstance(exc, aiohttp.ClientResponseError) and 400 <= exc.status < 500:
        return False
    return isinstance(exc, (aiohttp.ClientError, OSError, TimeoutError))


# Shared retry decorator: 3 attempts, 2s wait, skip 4xx
http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
