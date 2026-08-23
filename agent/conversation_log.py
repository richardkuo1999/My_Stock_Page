"""Persist every @mention conversation with the Agent to a JSONL file.

One JSON object per line (append-only) at `data/logs/agent_conversations.jsonl`
(same directory as bot.log). Kept out of git via `.gitignore` (all of `data/`
is ignored). This is a development/audit aid: it records what users asked, what
the Agent answered, and which tools the Agent used to get there.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from agent.bridge import AgentResult

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("data/logs/agent_conversations.jsonl")


def log_conversation(
    question: str,
    result: AgentResult,
    user_id: int | str | None = None,
    chat_id: int | str | None = None,
    path: Path = DEFAULT_PATH,
) -> None:
    """Append one @mention exchange to the conversation log.

    Best-effort: never raises. A logging failure must not break the reply to
    the user, so any exception is caught and logged as a warning.

    Args:
        question: The user's text after the @mention.
        result: The Agent's structured result (response + tools + usage).
        user_id: Telegram user id (optional).
        chat_id: Telegram chat id (optional).
        path: Override the log file path (mainly for tests).
    """
    try:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "chat_id": chat_id,
            "question": question,
            "response": result.response,
            "tools": [
                {"name": t.name, "parameters": t.parameters} for t in result.tools
            ],
            "status": result.status,
            "conversation_id": result.conversation_id,
            "usage": result.usage,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 — logging must never break the reply
        logger.warning("Failed to log agent conversation: %s", e)
