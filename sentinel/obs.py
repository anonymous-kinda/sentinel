"""Structured logging: a stable message plus fields.

    log = get_logger(__name__)
    log.info("Sync cycle failed", hub_id="hub", error="RequestTimeout")

The message is the low-cardinality key an operator searches and alerts on;
it never contains a variable. Values travel as fields, rendered as JSON
(one object per line, for Elastic or journald) or as key=value text.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
from typing import Any


class StructuredLogger:
    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _log(self, level: int, message: str, fields: dict[str, Any], exc_info: bool = False) -> None:
        if self._logger.isEnabledFor(level):
            self._logger.log(level, message, exc_info=exc_info, extra={"fields": fields}, stacklevel=3)

    def debug(self, message: str, /, **fields: Any) -> None:
        self._log(logging.DEBUG, message, fields)

    def info(self, message: str, /, **fields: Any) -> None:
        self._log(logging.INFO, message, fields)

    def warning(self, message: str, /, **fields: Any) -> None:
        self._log(logging.WARNING, message, fields)

    def error(self, message: str, /, **fields: Any) -> None:
        self._log(logging.ERROR, message, fields)

    def exception(self, message: str, /, **fields: Any) -> None:
        self._log(logging.ERROR, message, fields, exc_info=True)


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(logging.getLogger(name))


def _fields(record: logging.LogRecord) -> dict[str, Any]:
    return getattr(record, "fields", None) or {}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            **_fields(record),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = " ".join(f"{k}={v}" for k, v in _fields(record).items())
        return f"{base} {fields}" if fields else base


def configure_logging(fmt: str | None = None, level: str | None = None) -> None:
    """Install one Sentinel handler on the root logger (idempotent)."""
    fmt = fmt or os.environ.get("SENTINEL_LOG_FORMAT", "text")
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_sentinel", False)]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler._sentinel = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel((level or os.environ.get("SENTINEL_LOG_LEVEL", "INFO")).upper())
