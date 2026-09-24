"""Smoke test for the Compose stack: its DDIL properties, on real containers.

    make compose-up && make compose-smoke

Against the consoles the stack publishes on the host's loopback:

1. both nodes answer /api/health, as a hub and an edge of it, marked EXERCISE;
2. the hub's events reach the edge through sync and are re-assessed there:
   hub and edge agree, and every edge event is VERIFIED;
3. with the link set to DENIED through the edge's own /api/demo/link
   (compose_link.py), the edge measures DENIED and its console keeps
   answering, while an operator annotates an event;
4. with the link restored, hub and edge converge, the annotation made while
   denied included: it is signed by the edge, and the hub merges it only
   because both nodes enrolled their keys (identity.py);
5. OPSEC: a unit set on the edge (PUT 200) is 404 on the hub.

Convergence, the measured link state and the OPSEC unit are the DDIL
harness's own (scenarios.py), so "converged" means what it means in
docs/ddil-results.md. The run writes to the stack - one triage annotation,
and the exercise unit, set then removed - so run it on a fresh stack. It
always leaves the link CONNECTED.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import pathlib
import statistics
import sys
import time
from collections.abc import Callable

from sentinel.obs import configure_logging, get_logger

from .cluster import http, wait_until
from .compose import COMPOSE_FILE, EDGE_CONSOLE, HUB_CONSOLE
from .compose_link import set_link as compose_set_link
from .run import print_result
from .scenarios import (
    OPERATOR_EDGE,
    OPSEC_SETTLE_S,
    OPSEC_UNIT,
    Result,
    active,
    converged,
    link_state,
    status_of,
)

log = get_logger(__name__)

CONSOLE_REQUESTS = 40
CONSOLE_P95_MS = 200.0        # the DENIED scenario's bound
TRIAGE = "WATCH"


@dataclasses.dataclass(frozen=True)
class Stack:
    """The two consoles. Structurally what scenarios.py's helpers need of a Cluster."""

    hub: str = HUB_CONSOLE
    edge: str = EDGE_CONSOLE


@dataclasses.dataclass(frozen=True)
class Timeouts:
    health_s: float = 180.0    # first start: the reference library is assessed before /api/health answers
    converge_s: float = 120.0
    denied_s: float = 60.0     # NATS pings detect a black hole in ~15 s
    settle_s: float = OPSEC_SETTLE_S


class SmokeRun:
    def __init__(self, stack: Stack, set_link: Callable[[str], dict], timeouts: Timeouts):
        self.stack = stack
        self.set_link = set_link
        self.t = timeouts
        self.result = Result("COMPOSE-SMOKE")
        self.presets: list[str] = []
        self.event_id: str | None = None

    def __call__(self) -> Result:
        try:
            for step in (self.health, self.sync, self.denied, self.reconnect, self.opsec):
                if not step():
                    break
        except Exception as exc:  # noqa: BLE001 - a crashed step is a failed run, reported like one
            log.error("Smoke step crashed", error=type(exc).__name__, detail=str(exc))
            self.result.check("smoke test ran to completion", False, f"{type(exc).__name__}: {exc}")
        finally:
            self._leave_link_connected()
        return self.result

    # ------------------------------------------------------------ steps
    def health(self) -> bool:
        nodes = {}
        for name, base in (("hub", self.stack.hub), ("edge", self.stack.edge)):
            wait_until(lambda base=base: http("GET", f"{base}/api/health")["status"] == "ok", self.t.health_s,
                       what=f"{name} /api/health")
            nodes[name] = http("GET", f"{base}/api/node")
        hub, edge = nodes["hub"], nodes["edge"]
        self.result.check("both nodes are healthy", True, f"hub {hub['node_id']}, edge {edge['node_id']}")
        return self.result.check(
            "the hub runs as a hub, the edge as an edge of it, both marked EXERCISE",
            hub["role"] == "hub" and edge["role"] == "edge" and edge["hub_id"] == hub["node_id"]
            and all("EXERCISE" in n["marking"] for n in nodes.values()),
            f"hub {hub['role']} ({hub['marking']}), edge {edge['role']} of {edge['hub_id']} ({edge['marking']})",
        )

    def sync(self) -> bool:
        if not self._waited("the hub's events reached the edge through sync, every one VERIFIED",
                            lambda: converged(self.stack), self.t.converge_s):
            return False
        events = active(self.stack.edge)
        self.result.metrics["events"] = len(events)
        self.result.metrics["cdms"] = sum(e["cdm_count"] for e in events)
        return True

    def denied(self) -> bool:
        self._link("DENIED")
        if not self._waited("the edge measured the link as DENIED (measured, not configured)",
                            lambda: link_state(self.stack) == "DENIED", self.t.denied_s):
            return False
        latencies, error = self._console_latencies()
        if error:
            return self.result.check(self._console_check(), False, error)
        self.event_id = active(self.stack.edge)[0]["event_id"]
        http("POST", f"{self.stack.edge}/api/events/{self.event_id}/annotation",
             {"field": "triage_status", "value": TRIAGE}, OPERATOR_EDGE)
        p95 = statistics.quantiles(latencies, n=20)[18]
        self.result.metrics["edge_api_p95_ms_while_denied"] = round(p95, 1)
        return self.result.check(self._console_check(), p95 < CONSOLE_P95_MS,
                                 f"p95 {p95:.1f} ms over {len(latencies)} requests; {self.event_id} annotated meanwhile")

    def reconnect(self) -> bool:
        self._link("CONNECTED")
        if not self._waited("with the link restored, hub and edge converged (same events, all VERIFIED, same operator data)",
                            lambda: converged(self.stack), self.t.converge_s):
            return False
        ops = http("GET", f"{self.stack.hub}/api/events/{self.event_id}/ops")
        values = sorted({v["v"] for v in ops["annotations"]["triage_status"]["values"]})
        return self.result.check("the annotation made at the edge while DENIED is at the hub (signed, trusted, merged)",
                                 TRIAGE in values, f"hub: triage_status {values} on {self.event_id}")

    def opsec(self) -> bool:
        unit = f"{self.stack.edge}/api/passes/unit"
        put = status_of("PUT", unit, OPSEC_UNIT)
        time.sleep(self.t.settle_s)
        edge_get, hub_get = status_of("GET", unit), status_of("GET", f"{self.stack.hub}/api/passes/unit")
        status_of("DELETE", unit)
        return self.result.check("OPSEC: a unit set on the edge stays there (edge PUT 200, edge GET 200, hub GET 404)",
                                 (put, edge_get, hub_get) == (200, 200, 404),
                                 f"edge PUT {put}, edge GET {edge_get}, hub GET {hub_get}")

    # ---------------------------------------------------------- helpers
    def _waited(self, name: str, predicate: Callable[[], bool], timeout: float) -> bool:
        try:
            wait_until(predicate, timeout, what=name)
        except TimeoutError as exc:
            return self.result.check(name, False, str(exc))
        return self.result.check(name, True)

    def _link(self, preset: str) -> None:
        self.presets.append(preset)
        status = self.set_link(preset)
        log.info("Link preset applied", preset=preset, enabled=status.get("enabled"))

    def _console_latencies(self) -> tuple[list[float], str | None]:
        latencies = []
        try:
            for _ in range(CONSOLE_REQUESTS):
                t0 = time.monotonic()
                http("GET", f"{self.stack.edge}/api/events")
                latencies.append((time.monotonic() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001 - an unanswered request is the failure being measured
            return latencies, f"request {len(latencies) + 1} of {CONSOLE_REQUESTS} failed: {type(exc).__name__}: {exc}"
        return latencies, None

    @staticmethod
    def _console_check() -> str:
        return f"the edge console kept answering while DENIED (p95 < {CONSOLE_P95_MS:.0f} ms)"

    def _leave_link_connected(self) -> None:
        if not self.presets or self.presets[-1] == "CONNECTED":
            return
        try:
            self._link("CONNECTED")
        except Exception as exc:  # noqa: BLE001 - reported, and the run already failed
            log.error("Link not restored", error=type(exc).__name__, detail=str(exc))
            self.result.check("the link was left CONNECTED", False, f"{type(exc).__name__}: {exc}")


DEFAULT_TIMEOUTS = Timeouts()


def run(stack: Stack, set_link: Callable[[str], dict], timeouts: Timeouts = DEFAULT_TIMEOUTS) -> Result:
    return SmokeRun(stack, set_link, timeouts)()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the running Compose stack.")
    parser.add_argument("--hub", default=HUB_CONSOLE)
    parser.add_argument("--edge", default=EDGE_CONSOLE)
    parser.add_argument("--compose-file", type=pathlib.Path, default=COMPOSE_FILE)
    args = parser.parse_args(argv)
    configure_logging()
    print("=== COMPOSE SMOKE", flush=True)
    result = run(Stack(args.hub, args.edge), functools.partial(compose_set_link, compose_file=args.compose_file))
    print_result(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
