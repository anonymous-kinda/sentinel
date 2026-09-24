"""Structured logging: stable, low-cardinality messages; values as fields.

    log.info("Sync cycle failed", hub_id="hub", error="RequestTimeout")

The message is the thing you search and alert on, so it never contains a
variable. Everything variable travels as a field.
"""

import json
import logging

import pytest

from sentinel.obs import JsonFormatter, TextFormatter, configure_logging, get_logger


@pytest.fixture
def captured(caplog):
    caplog.set_level(logging.DEBUG, logger="sentinel.test")
    return caplog


def test_message_stays_stable_and_values_become_fields(captured):
    get_logger("sentinel.test").info("Sync cycle failed", hub_id="hub", error="RequestTimeout")
    record = captured.records[-1]
    assert record.getMessage() == "Sync cycle failed"
    assert record.fields == {"hub_id": "hub", "error": "RequestTimeout"}


def test_every_level_carries_fields(captured):
    log = get_logger("sentinel.test")
    for level in ("debug", "info", "warning", "error"):
        getattr(log, level)("Level check", level=level)
    assert [r.fields["level"] for r in captured.records[-4:]] == ["debug", "info", "warning", "error"]


def test_exception_logs_traceback_and_fields(captured):
    try:
        raise ValueError("boom")
    except ValueError:
        get_logger("sentinel.test").exception("Responder failed", subject="sync.hub.fetch")
    record = captured.records[-1]
    assert record.exc_info is not None
    assert record.fields == {"subject": "sync.hub.fetch"}


def test_json_formatter_emits_one_object_per_line():
    record = logging.LogRecord("sentinel.x", logging.WARNING, __file__, 1, "Leaf reconnect slow", None, None)
    record.fields = {"seconds": 4.8, "path": object()}
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "Leaf reconnect slow"
    assert out["level"] == "warning"
    assert out["logger"] == "sentinel.x"
    assert out["seconds"] == 4.8
    assert isinstance(out["path"], str), "non-JSON values are stringified, not dropped"
    assert "ts" in out


def test_text_formatter_appends_fields_as_key_value():
    record = logging.LogRecord("sentinel.x", logging.INFO, __file__, 1, "Library loaded", None, None)
    record.fields = {"events": 53}
    assert TextFormatter().format(record).endswith("Library loaded events=53")


def test_configure_logging_is_idempotent():
    configure_logging("json")
    configure_logging("json")
    handlers = [h for h in logging.getLogger().handlers if getattr(h, "_sentinel", False)]
    assert len(handlers) == 1
    assert isinstance(handlers[0].formatter, JsonFormatter)
