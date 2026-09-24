"""The Compose smoke test (harness/compose_smoke.py) and the link control it
drives (harness/compose_link.py), against a simulated stack.

The live run needs Docker (ci.yml, job compose-smoke). Here a fake hub and
edge answer the same HTTP calls, so each check is shown to pass on a healthy
stack and to fail on the fault it exists to catch.
"""

import io
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import pytest

from harness import compose_link, compose_smoke, scenarios
from harness.compose import COMPOSE_FILE
from harness.compose_smoke import Stack, Timeouts

FAST = Timeouts(health_s=2, converge_s=2, denied_s=1, settle_s=0)
EVENT = {"event_id": "E-1", "cdm_count": 3, "verification": "VERIFIED"}


class FakeStack:
    """Two nodes as the smoke test sees them. The edge's annotations reach
    the hub whenever the link is up and the hub trusts the edge's key."""

    hub = "http://hub.test"
    edge = "http://edge.test"

    def __init__(self, *, measures_denied=True, trusts_edge=True, hub_has_unit=False, console_fails_denied=False):
        self.measures_denied = measures_denied
        self.trusts_edge = trusts_edge
        self.hub_has_unit = hub_has_unit
        self.console_fails_denied = console_fails_denied
        self.presets: list[str] = []
        self.annotations = {"hub": set(), "edge": set()}
        self.edge_unit = None

    @property
    def preset(self) -> str:
        return self.presets[-1] if self.presets else "CONNECTED"

    def set_link(self, preset: str) -> dict:
        self.presets.append(preset)
        return {"preset": preset, "enabled": preset != "DENIED", "toxics": []}

    def http(self, method, url, body=None, headers=None, timeout=10.0):
        if self.preset != "DENIED" and self.trusts_edge:
            self.annotations["hub"] |= self.annotations["edge"]
        parts = urllib.parse.urlsplit(url)
        node = "hub" if parts.netloc == "hub.test" else "edge"
        if node == "edge" and parts.path == "/api/events" and self.preset == "DENIED" and self.console_fails_denied:
            raise urllib.error.URLError("connection refused")
        return self._route(method, parts.path, node, url, body)

    def _route(self, method, path, node, url, body):
        node_id = {"hub": "hub", "edge": "edge-alpha"}[node]
        if (method, path) == ("GET", "/api/health"):
            return {"status": "ok", "node_id": node_id}
        if (method, path) == ("GET", "/api/node"):
            return {"node_id": node_id, "role": node, "marking": "UNCLASSIFIED // EXERCISE",
                    "hub_id": "hub" if node == "edge" else None}
        if (method, path) == ("GET", "/api/events"):
            return [dict(EVENT)]
        if (method, path) == ("GET", "/api/ops/digest"):
            return {"log": "same", "annotations": repr(sorted(self.annotations[node]))}
        if (method, path) == ("GET", "/api/link"):
            denied = self.preset == "DENIED" and self.measures_denied
            return {"monitor": {"state": "DENIED" if denied else "CONNECTED"}}
        if (method, path) == ("POST", "/api/events/E-1/annotation"):
            self.annotations[node].add(body["value"])
            return {}
        if (method, path) == ("GET", "/api/events/E-1/ops"):
            values = [{"v": v} for v in sorted(self.annotations[node])]
            return {"annotations": {"triage_status": {"values": values, "conflict": False}}}
        return self._unit(method, node, url, body)

    def _unit(self, method, node, url, body):
        if method == "PUT" and node == "edge":
            self.edge_unit = body
            return body
        if method == "DELETE" and node == "edge":
            self.edge_unit = None
            return None
        held = self.edge_unit if node == "edge" else (self.edge_unit if self.hub_has_unit else None)
        if method == "GET" and held:
            return held
        raise urllib.error.HTTPError(url, 404, "no unit is set on this node", None, None)


@pytest.fixture
def smoke(monkeypatch):
    def run(**faults):
        fake = FakeStack(**faults)
        monkeypatch.setattr(compose_smoke, "http", fake.http)
        monkeypatch.setattr(scenarios, "http", fake.http)
        return fake, compose_smoke.run(Stack(fake.hub, fake.edge), fake.set_link, FAST)
    return run


def failed(result) -> list[str]:
    return [a["name"] for a in result.assertions if not a["passed"]]


# ------------------------------------------------------------------- smoke
def test_a_healthy_stack_passes_every_check(smoke):
    fake, result = smoke()
    assert result.passed, result.assertions
    assert [a["name"] for a in result.assertions] == [
        "both nodes are healthy",
        "the hub runs as a hub, the edge as an edge of it, both marked EXERCISE",
        "the hub's events reached the edge through sync, every one VERIFIED",
        "the edge measured the link as DENIED (measured, not configured)",
        "the edge console kept answering while DENIED (p95 < 200 ms)",
        "with the link restored, hub and edge converged (same events, all VERIFIED, same operator data)",
        "the annotation made at the edge while DENIED is at the hub (signed, trusted, merged)",
        "OPSEC: a unit set on the edge stays there (edge PUT 200, edge GET 200, hub GET 404)",
    ]
    assert fake.presets == ["DENIED", "CONNECTED"]
    assert fake.edge_unit is None, "the exercise unit is removed afterwards"


def test_an_edge_that_never_measures_denied_fails_and_the_link_is_restored(smoke):
    fake, result = smoke(measures_denied=False)
    assert failed(result) == ["the edge measured the link as DENIED (measured, not configured)"]
    assert fake.presets == ["DENIED", "CONNECTED"]


def test_an_edge_console_that_stops_answering_while_denied_fails(smoke):
    fake, result = smoke(console_fails_denied=True)
    assert failed(result) == ["the edge console kept answering while DENIED (p95 < 200 ms)"]
    assert "URLError" in result.assertions[-1]["detail"]
    assert fake.presets == ["DENIED", "CONNECTED"]


def test_a_hub_that_does_not_trust_the_edge_never_converges(smoke):
    fake, result = smoke(trusts_edge=False)
    assert failed(result) == ["with the link restored, hub and edge converged (same events, all VERIFIED, same operator data)"]
    assert fake.presets[-1] == "CONNECTED"


def test_a_unit_that_reaches_the_hub_fails_the_opsec_check(smoke):
    _, result = smoke(hub_has_unit=True)
    assert failed(result) == ["OPSEC: a unit set on the edge stays there (edge PUT 200, edge GET 200, hub GET 404)"]


def test_a_step_that_crashes_is_a_failed_run_not_a_traceback(smoke, monkeypatch):
    monkeypatch.setattr(compose_smoke, "active", lambda base: [])
    fake, result = smoke()
    assert "smoke test ran to completion" in failed(result)
    assert fake.presets[-1] == "CONNECTED"


def test_main_reports_each_check_and_exits_non_zero_on_a_failure(monkeypatch, capsys):
    result = scenarios.Result("COMPOSE-SMOKE")
    result.check("both nodes are healthy", True)
    result.check("OPSEC: a unit set on the edge stays there", False, "hub GET 200")
    monkeypatch.setattr(compose_smoke, "run", lambda stack, set_link: result)
    assert compose_smoke.main([]) == 1
    out = capsys.readouterr().out
    assert "[PASS] both nodes are healthy" in out and "[FAIL] OPSEC: a unit set on the edge stays there - hub GET 200" in out


# -------------------------------------------------------------------- link
def test_the_link_command_runs_inside_the_edge_container():
    assert compose_link.link_command("DENIED", COMPOSE_FILE) == [
        "docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", "edge",
        "python", "-c", compose_link.SNIPPET, "DENIED",
    ]


def test_the_snippet_posts_the_preset_to_the_edges_own_loopback(monkeypatch, capsys):
    sent = []

    def urlopen(request, timeout):
        sent.append(request)
        return io.BytesIO(b'{"preset": "DENIED"}')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sys, "argv", ["-c", "DENIED"])
    exec(compile(compose_link.SNIPPET, "<snippet>", "exec"), {})
    (request,) = sent
    assert (request.full_url, request.get_method()) == ("http://127.0.0.1:8000/api/demo/link", "POST")
    assert json.loads(request.data) == {"preset": "DENIED"}
    assert json.loads(capsys.readouterr().out) == {"preset": "DENIED"}


def test_set_link_returns_the_emulators_status():
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout='{"preset": "LIMITED", "enabled": true}\n', stderr="")

    assert compose_link.set_link("LIMITED", run=run) == {"preset": "LIMITED", "enabled": True}


def test_a_refused_preset_raises_with_what_docker_said():
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP Error 403: Forbidden\n")

    with pytest.raises(compose_link.LinkControlError, match="403"):
        compose_link.set_link("DENIED", run=run)


def test_an_unknown_preset_is_refused_before_anything_runs():
    def run(cmd, **kwargs):
        raise AssertionError("nothing should run")

    with pytest.raises(ValueError, match="FOGGY"):
        compose_link.set_link("FOGGY", run=run)


def test_the_command_line_prints_the_applied_status(monkeypatch, capsys):
    monkeypatch.setattr(compose_link, "set_link", lambda preset, compose_file: {"preset": preset})
    assert compose_link.main(["DEGRADED"]) == 0
    assert json.loads(capsys.readouterr().out) == {"preset": "DEGRADED"}
