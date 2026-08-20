"""Structured, redacted logging for the native engine process."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        # Do not serialize bearer tokens, API keys or full request bodies into
        # the user-owned log file/stdout stream.
        for secret in ("bearerToken", "bearer_token", "Authorization", "api_key", "API_KEY"):
            if secret in message:
                message = f"[redacted log message containing {secret}]"
                break
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, ensure_ascii=True)


def configure_logging(log_path: str | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_path:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        handlers.append(file_handler)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    formatter = JsonLogFormatter()
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
