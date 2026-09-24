"""`make ai-live-check`: one real call per configured hosted-AI provider.

The production adapters (JevRouter.from_env, ClaudeNarrator.from_env) run
through their real SDKs against injected mock transports, on the exercise
scenario's routing context and real tool facts - so these tests pin what
the command sends and reports with no network and no API key. What a real
key returns is only known once one is set; nothing here stands in for it.
"""

import hashlib
import logging
import os
import pathlib
import subprocess
import sys

import httpx2
import pytest

from scripts import ai_live_check
from scripts.ai_eval import exercise_service, routing_context
from tests.ai.test_narrate_claude import message as claude_message
from tests.ai.test_router_jev import answer as jev_answer
from tests.makefile import dry_run

ROOT = pathlib.Path(__file__).resolve().parents[2]
JEV, CLAUDE = "TYPESAFE_API_KEY", "ANTHROPIC_API_KEY"
# Distinctive values, so a leak anywhere in output or logs is unmistakable.
KEYS = {JEV: "ts-live-check-SECRET-7f3a", CLAUDE: "sk-ant-live-check-SECRET-9c1e"}
HEADERS = {JEV: "Jev routing", CLAUDE: "Claude narration"}
QUESTION = "How risky is the 118 conjunction?"          # eval case ass-01
UNGROUNDED = "EX-DEB 118 is RED: Pc 7.7×10⁻² (Foster-Estes 2D)."


@pytest.fixture(scope="module")
def context():
    return routing_context(exercise_service())


@pytest.fixture(scope="module")
def event_118(context):
    return next(e["event_id"] for e in context.events if e["event_id"].split("-")[1] == "99118")


class Wire:
    """Mock transports for both providers, recording every request."""

    def __init__(self, event_id: str):
        self.requests: dict[str, list[httpx2.Request]] = {JEV: [], CLAUDE: []}
        self.status = {JEV: 200, CLAUDE: 200}
        self.timeout = {JEV: False, CLAUDE: False}
        self.body = {
            JEV: jev_answer(tool="get_assessment", event=event_id),
            CLAUDE: claude_message(),
        }
        self.request_id = {JEV: ("x-typesafe-request-id", "req_jev"), CLAUDE: ("request-id", "req_claude")}

    def transport(self, key_var: str) -> httpx2.MockTransport:
        def handler(request: httpx2.Request) -> httpx2.Response:
            self.requests[key_var].append(request)
            if self.timeout[key_var]:
                raise httpx2.ReadTimeout("timed out", request=request)
            body = self.body[key_var] if self.status[key_var] == 200 else rejected(key_var)
            return httpx2.Response(self.status[key_var], json=body, headers=[self.request_id[key_var]])

        return httpx2.MockTransport(handler)


def rejected(key_var: str) -> dict:
    """An error body that echoes the key, as a careless service might."""
    detail = f"invalid key {KEYS[key_var]}"
    if key_var == CLAUDE:
        return {"type": "error", "error": {"type": "authentication_error", "message": detail}}
    return {"error": {"message": detail}}


@pytest.fixture
def wire(event_118):
    return Wire(event_118)


@pytest.fixture
def keys(monkeypatch):
    for key_var, value in KEYS.items():
        monkeypatch.setenv(key_var, value)


def check(wire: Wire, capsys) -> tuple[int, str]:
    code = ai_live_check.main(jev_transport=wire.transport(JEV), claude_transport=wire.transport(CLAUDE))
    return code, capsys.readouterr().out


def block(out: str, key_var: str) -> str:
    """One provider's part of the report: its header line up to the blank line."""
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(HEADERS[key_var] + ":"))
    end = next((i for i in range(start, len(lines)) if not lines[i].strip()), len(lines))
    return "\n".join(lines[start:end])


# ------------------------------------------------------------ both keys set
def test_with_both_keys_it_makes_one_real_call_to_each_and_reports_it(keys, wire, capsys, context, event_118):
    code, out = check(wire, capsys)

    assert code == 0
    [jev_request], [claude_request] = wire.requests[JEV], wire.requests[CLAUDE]
    assert jev_request.headers["authorization"] == f"Bearer {KEYS[JEV]}", "the production client read the key"
    assert claude_request.headers["x-api-key"] == KEYS[CLAUDE]
    jev_body = jev_request.read().decode()
    assert QUESTION in jev_body and all(e["event_id"] in jev_body for e in context.events)
    claude_body = claude_request.read().decode()
    assert f'\\"event_id\\": \\"{event_118}\\"' in claude_body, "real get_assessment facts, not a hand-written copy"

    jev = block(out, JEV)
    assert jev.startswith("Jev routing: ok")
    assert "get_assessment" in jev and event_118 in jev
    assert "confidence  0.80" in jev
    assert "latency" in jev and " ms" in jev
    assert "request" in jev and "response" in jev and "bytes" in jev
    assert "req_jev" in jev

    claude = block(out, CLAUDE)
    assert claude.startswith("Claude narration: ok")
    assert "claude-opus-5" in claude
    assert "grounding   passed" in claude
    assert "input 812, output 64" in claude
    assert claude_message()["content"][1]["text"] in claude, "the answer itself is shown"


def test_the_last_line_is_the_next_command(keys, wire, capsys):
    _, out = check(wire, capsys)
    assert out.rstrip().splitlines()[-1].startswith("Next: make ai-eval")


def test_an_ungrounded_answer_is_reported_as_the_assistant_would_withhold_it(keys, wire, capsys):
    wire.body[CLAUDE] = claude_message(text=UNGROUNDED)
    code, out = check(wire, capsys)
    claude = block(out, CLAUDE)
    assert "grounding   failed" in claude and "7.7×10⁻²" in claude
    assert "template" in claude
    assert code == 0, "the call worked; the guard doing its job is not a readiness failure"


def test_it_writes_nothing_under_docs(keys, wire, capsys):
    """Publishing eval numbers is make ai-eval's job, never this check's."""

    def snapshot():
        return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "docs").rglob("*") if p.is_file()}

    before = snapshot()
    check(wire, capsys)
    assert snapshot() == before


# ------------------------------------------------------------- missing keys
@pytest.mark.parametrize("missing", [JEV, CLAUDE])
def test_a_missing_key_is_named_with_what_the_check_would_do_and_is_not_a_failure(
    missing, keys, wire, capsys, monkeypatch
):
    monkeypatch.delenv(missing)
    code, out = check(wire, capsys)

    assert code == 0, "a key that is not set yet is not a failure"
    assert wire.requests[missing] == [], "no call without a key"
    skipped = block(out, missing)
    assert skipped.startswith(f"{HEADERS[missing]}: not configured")
    assert f"{missing} is not set" in skipped
    assert "docs/technical-guide.md" in skipped
    would = {JEV: ("JevRouter.from_env()", QUESTION, "confidence"), CLAUDE: ("ClaudeNarrator.from_env()", "grounding", "tokens")}
    assert all(phrase in skipped for phrase in would[missing])

    other = next(k for k in KEYS if k != missing)
    assert len(wire.requests[other]) == 1 and block(out, other).startswith(f"{HEADERS[other]}: ok")


def test_with_no_keys_no_call_is_made_and_it_says_how_to_set_them(wire, capsys, monkeypatch):
    for key_var in KEYS:
        monkeypatch.delenv(key_var, raising=False)
    code, out = check(wire, capsys)

    assert code == 0
    assert wire.requests == {JEV: [], CLAUDE: []}
    assert ".env.example" in out
    assert out.rstrip().splitlines()[-1].startswith("Next: make ai-eval")


# ---------------------------------------------------- configured, but fails
@pytest.mark.parametrize(
    "key_var,sdk_error", [(JEV, "TypeSafeAuthenticationError"), (CLAUDE, "AuthenticationError")]
)
def test_a_rejected_key_exits_non_zero_naming_the_adapters_reason(key_var, sdk_error, keys, wire, capsys, caplog):
    wire.status[key_var] = 401
    code, out = check(wire, capsys)

    assert code == 1
    failed = block(out, key_var)
    assert failed.startswith(f"{HEADERS[key_var]}: FAILED")
    assert "reason      authentication" in failed
    other = next(k for k in KEYS if k != key_var)
    assert block(out, other).startswith(f"{HEADERS[other]}: ok"), "one failure does not hide the other result"
    [logged] = [r for r in caplog.records if r.getMessage() == "Hosted AI live check failed"]
    assert logged.fields == {"provider": HEADERS[key_var], "reason": "authentication", "error": sdk_error}


@pytest.mark.parametrize(
    "key_var,reason",
    [
        # The TypeSafe SDK raises its timeout as a connection error, and the Jev
        # adapter names both `unreachable`; the Claude adapter names it `timeout`.
        (JEV, "unreachable"),
        (CLAUDE, "timeout"),
    ],
)
def test_a_timeout_exits_non_zero_naming_the_adapters_reason(key_var, reason, keys, wire, capsys):
    wire.timeout[key_var] = True
    code, out = check(wire, capsys)

    assert code == 1
    assert len(wire.requests[key_var]) == 1, "one attempt, as in production: no retries"
    assert f"reason      {reason}" in block(out, key_var)


# ------------------------------------------------------------------ secrets
@pytest.mark.parametrize("status", [200, 401])
def test_the_keys_never_reach_output_or_logs(status, keys, wire, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    wire.status = {JEV: status, CLAUDE: status}
    ai_live_check.main(jev_transport=wire.transport(JEV), claude_transport=wire.transport(CLAUDE))
    captured = capsys.readouterr()

    assert wire.requests[JEV] and wire.requests[CLAUDE], "both keys were used"
    for secret in KEYS.values():
        assert secret not in captured.out
        assert secret not in captured.err
        assert [r.name for r in caplog.records if secret in repr(vars(r))] == []
    # The SDK wire logs (bodies at DEBUG) were held at INFO only while the calls ran.
    assert logging.getLogger("typesafe_sdk").level == logging.NOTSET


# ------------------------------------------------------ the command itself
def test_the_command_runs_without_keys_and_exits_zero():
    """The real entry point, keys removed: what `make ai-live-check` prints today."""
    env = {k: v for k, v in os.environ.items() if k not in KEYS}
    done = subprocess.run(
        [sys.executable, "scripts/ai_live_check.py"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    assert f"{JEV} is not set" in done.stdout and f"{CLAUDE} is not set" in done.stdout
    assert done.stdout.rstrip().splitlines()[-1].startswith("Next: make ai-eval")


def test_make_ai_live_check_runs_the_script():
    assert dry_run("ai-live-check") == ["uv run python scripts/ai_live_check.py"]
