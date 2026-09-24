"""`sentinel serve` runs with structured logging and no access-log noise,
at the level the operator asked for: --log-level, else SENTINEL_LOG_LEVEL,
else info."""

import logging

import pytest

from sentinel import cli


@pytest.fixture
def served(monkeypatch):
    """Run `sentinel serve` with uvicorn stubbed out; return what it was handed."""
    calls = {}
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)

    def fake_run(app, **kwargs):
        calls.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setenv("SENTINEL_EXERCISE", "0")
    monkeypatch.setenv("SENTINEL_LIBRARY", "0")
    monkeypatch.setenv("SENTINEL_VAR", "/tmp/sentinel-cli-test-var")
    monkeypatch.delenv("SENTINEL_LOG_LEVEL", raising=False)

    def serve(*flags: str) -> dict:
        assert cli.main(["serve", "--port", "9999", *flags]) == 0
        return calls

    yield serve
    root.setLevel(level)
    root.handlers[:] = handlers


def test_serve_installs_structured_logging_and_hands_uvicorn_no_log_config(served, monkeypatch):
    monkeypatch.setenv("SENTINEL_LOG_FORMAT", "json")
    calls = served()
    assert calls["log_config"] is None, "uvicorn must not replace Sentinel's handler"
    assert calls["access_log"] is False
    assert any(getattr(h, "_sentinel", False) for h in logging.getLogger().handlers)


def test_without_a_flag_or_variable_serve_logs_at_info(served):
    assert served()["log_level"] == "info"
    assert logging.getLogger().level == logging.INFO


def test_serve_honours_sentinel_log_level_when_no_flag_is_given(served, monkeypatch):
    monkeypatch.setenv("SENTINEL_LOG_LEVEL", "WARNING")
    assert served()["log_level"] == "warning"
    assert logging.getLogger().level == logging.WARNING


def test_the_flag_wins_over_the_variable(served, monkeypatch):
    monkeypatch.setenv("SENTINEL_LOG_LEVEL", "warning")
    assert served("--log-level", "debug")["log_level"] == "debug"
    assert logging.getLogger().level == logging.DEBUG
