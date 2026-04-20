import logging
import os
from logging.config import dictConfig


def setup_logging():
    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "simple": {"format": "[%(levelname)s] %(message)s"},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": "simple",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "DEBUG",
                "formatter": "standard",
                "filename": "logs/app.log",
                "maxBytes": 10 * 1024 * 1024,  # 10 MB
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "root": {
                "level": "INFO",
                "handlers": ["console", "file"],
            },
            "analysis_bot": {
                "level": "DEBUG",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "uvicorn": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "apscheduler": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "telegram": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "httpx": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "apscheduler.executors.default": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },
    }

    dictConfig(LOGGING_CONFIG)
    logging.info("Logging configured successfully.")
