from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path


SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:cookie|token|api[_-]?key)\s*[:=]\s*)[^\s,;]+"),
)


class SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self.secrets = tuple(secret for secret in secrets if len(secret) >= 6)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        for pattern in SENSITIVE_PATTERNS:
            message = pattern.sub(r"\1[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(
    level: str,
    secrets: Iterable[str] = (),
    *,
    file_path: str | None = None,
    max_bytes: int = 5_000_000,
    backup_count: int = 7,
) -> None:
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    redaction = SecretRedactionFilter(secrets)
    handlers: list[logging.Handler] = []

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(redaction)
    handlers.append(stream_handler)

    if file_path:
        path = Path(file_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction)
        handlers.append(file_handler)

    root = logging.getLogger()
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level.upper())

    # HTTPX logs full request URLs at INFO level. MTop URLs include request
    # signatures and volatile query parameters, so keep them out of routine
    # application logs while retaining warnings and errors.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
