"""Logging configuration."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("data/logs")
LOG_FILE = LOG_DIR / "bot.log"
MAX_BYTES = 5 * 1024 * 1024  # 5MB
BACKUP_COUNT = 5
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging() -> None:
    """Configure logging: INFO+ to stdout, WARNING+ to file with rotation."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Clear any existing handlers (e.g. from basicConfig)
    root.handlers.clear()

    # Console handler: INFO+
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(console)

    # File handler: WARNING+ with rotation
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(file_handler)
