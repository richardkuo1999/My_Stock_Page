"""Shared aiohttp helpers with proper SSL configuration."""

import logging
import ssl

import aiohttp
import certifi
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

_SSL_CTX = ssl.create_default_context(cafile=certifi.where())
_session: aiohttp.ClientSession | None = None
_logger = logging.getLogger(__name__)


def create_session(**kwargs) -> aiohttp.ClientSession:
    """Create a new aiohttp.ClientSession (for callers that need a dedicated session)."""
    connector = kwargs.pop("connector", None)
    if connector is None:
        connector = aiohttp.TCPConnector(ssl=_SSL_CTX)
    return aiohttp.ClientSession(connector=connector, **kwargs)


def get_session() -> aiohttp.ClientSession:
    """Return the shared singleton session (lazy-created)."""
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(ssl=_SSL_CTX, limit=100)
        _session = aiohttp.ClientSession(connector=connector)
        _logger.debug("Created shared aiohttp session")
    return _session


async def close_session() -> None:
    """Close the shared singleton session (call on app shutdown)."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _logger.debug("Closed shared aiohttp session")
    _session = None


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
