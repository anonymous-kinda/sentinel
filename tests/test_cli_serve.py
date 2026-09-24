"""`sentinel serve` runs with structured logging and no access-log noise."""

import logging

from sentinel import cli


def test_serve_installs_structured_logging_and_hands_uvicorn_no_log_config(monkeypatch):
    calls = {}

    def fake_run(app, **kwargs):
        calls.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setenv("SENTINEL_LOG_FORMAT", "json")
    monkeypatch.setenv("SENTINEL_EXERCISE", "0")
    monkeypatch.setenv("SENTINEL_LIBRARY", "0")
    monkeypatch.setenv("SENTINEL_VAR", "/tmp/sentinel-cli-test-var")

    assert cli.main(["serve", "--port", "9999"]) == 0
    assert calls["log_config"] is None, "uvicorn must not replace Sentinel's handler"
    assert calls["access_log"] is False
    assert any(getattr(h, "_sentinel", False) for h in logging.getLogger().handlers)
