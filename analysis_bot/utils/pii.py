from __future__ import annotations

import hashlib
from typing import Optional, Union


def redact_telegram_id(value: Union[int, str], *, salt: Optional[str] = None) -> str:
    """
    Redact Telegram identifiers (chat_id/user_id) for logs.

    - If salt is provided: return a short, stable, non-reversible hash token.
    - If no salt: return a masked representation that keeps only last 4 characters.
    """
    if value is None:
        return "<redacted>"

    raw = str(value).strip()
    if not raw:
        return "<redacted>"

    salt = (salt or "").strip()
    if salt:
        digest = hashlib.sha256(f"{salt}:{raw}".encode("utf-8")).hexdigest()
        return f"tgid_{digest[:10]}"

    # Mask mode (no salt configured)
    tail = raw[-4:] if len(raw) >= 4 else raw
    return f"tgid_****{tail}"

