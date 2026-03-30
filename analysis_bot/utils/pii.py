from __future__ import annotations

import hashlib


def redact_telegram_id(value: int | str, *, salt: str | None = None) -> str:
    """
    Redact Telegram identifiers (chat_id/user_id) for logs to protect privacy.

    - If salt is provided: returns a short, stable, non-reversible hash token.
      Use a strong, secret salt (e.g. 16+ chars) to prevent rainbow table attacks.
    - If no salt: returns a masked representation that keeps only last 4 characters.
    """
    if value is None:
        return "<redacted:null>"

    raw = str(value).strip()
    if not raw:
        return "<redacted:empty>"

    salt = (salt or "").strip()
    if salt:
        # Use HMAC or just a salt + hash. Salted hash is usually enough for IDs.
        digest = hashlib.sha256(f"{salt}:{raw}".encode()).hexdigest()
        # 10 chars of hex gives 16^10 (~1 trillion) possibilities, safe for ID collision
        return f"tgid_{digest[:10]}"

    # Mask mode (no salt configured) - LESS SECURE but better than plain ID
    if len(raw) <= 4:
        return f"tgid_{raw}"
    tail = raw[-4:]
    return f"tgid_****{tail}"
