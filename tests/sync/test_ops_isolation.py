"""A failure in the operator-data exchange is not a link failure, and it
does not stop the manifest and records behind it.

The exchange runs first in each cycle. Before it was isolated, one
IntegrityError, or the empty `responder-failed` reply a NATS hub sends when
its responder raises, ended the cycle: the manifest and records were never
pulled, and the link monitor counted a failure every cycle, so a link that
was up read DEGRADED, then DENIED.
"""

from __future__ import annotations

from sentinel.bus import subjects
from sentinel.crdt import TrustStore
from sentinel.linkstate import LinkState
from sentinel.ops import OpsService

from .conftest import KEYS, TRUST, run


def held(node) -> set[str]:
    return {row.sha256[:16] for row in node.conj.store.all_cdms()}


def announced(node) -> set[str]:
    return {sha for compact in node.conj.manifest() for sha, _, _ in compact["c"]}


def test_a_node_that_lost_its_database_but_kept_its_key_still_syncs_records(pair):
    """It starts reusing dots: its new note is signed at a dot the hub holds
    with other content, which raises IntegrityError by design (ADR-005)."""
    hub, edge, agent, clock = pair
    for n in range(3):
        run(edge.ops.append("EV1", "NOTE", {"text": f"first life {n}"}, "op@alpha"))
    run(agent.exchange_ops())
    assert len(hub.ops.log.entries) == 3

    reborn = OpsService("alpha", KEYS["alpha"], TrustStore(TRUST), hub.ops.bus, clock)
    run(reborn.append("EV1", "NOTE", {"text": "second life"}, "op@alpha"))
    agent.ops = reborn
    for _ in range(2):
        run(agent.step())

    assert held(edge) == announced(hub), "the records behind the exchange never came"
    assert agent.link.state is LinkState.CONNECTED
    assert agent.status()["last_cycle"]["ops"]["error"] == "IntegrityError"


def test_a_hub_that_cannot_answer_operator_data_still_serves_records(pair):
    """What NatsBus sends when the hub's responder raises: an empty body."""
    hub, edge, agent, clock = pair

    async def responder_failed(msg):
        return b"", {"Sentinel-Error": "responder-failed"}

    run(hub.ops.bus.serve(subjects.ops_exchange("hub"), responder_failed))
    for _ in range(2):
        run(agent.step())

    assert held(edge) == announced(hub)
    assert agent.link.state is LinkState.CONNECTED
    assert agent.status()["last_cycle"]["ops"] == {"error": "HubError", "detail": "responder-failed"}
