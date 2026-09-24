"""Subject namespace. One place, so the ICD (docs/icd/asyncapi.yaml) can be
checked against it (tests/docs/test_asyncapi.py).

Node-local (never cross a leaf link - ADR-009; each node subscribes only to
its own, and the edge's leafnode denies node.> both ways):

    node.<node_id>.cdm.accepted.<event>   a CDM was admitted and assessed
    node.<node_id>.cdm.rejected           a CDM was quarantined
    node.<node_id>.ops.changed            operator data changed (write or CRDT merge)
    node.<node_id>.sync.progress          sync agent state (edge)
    node.<node_id>.sync.arrival           one record arrived from the hub (edge)
    node.<node_id>.link.state             measured link state changed (edge)
    node.<node_id>.link.emulation         link-emulation preset applied (demo only)
    node.<node_id>.passes.updated         pass inputs moved (no unit, no coordinates)

Each is published with a Sentinel-Kind header equal to its kind, which the
console's server-sent event stream uses as the event name.

Cross-node, request/reply, served by the hub:

    sync.<hub_id>.manifest                event summaries (P0)
    sync.<hub_id>.fetch                   one record, its original bytes
    ops.<hub_id>.exchange                 CRDT anti-entropy, both directions

Never exported across a leaf (enforced by leafnode permissions, M3):

    unit.>, passes.>                      ground-unit position and pass windows
"""

NODE_EVENTS = (
    "cdm.accepted",
    "cdm.rejected",
    "ops.changed",
    "sync.progress",
    "sync.arrival",
    "link.state",
    "link.emulation",
    "passes.updated",
)


def token(value: str) -> str:
    """Make a value safe as a single subject token."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value) or "_"


def local(node_id: str, kind: str, *detail: str) -> str:
    """node.<node_id>.<kind>[.<detail>...]. A kind the ICD does not describe
    is refused: an undocumented subject is a bug, not a feature."""
    if kind not in NODE_EVENTS:
        raise ValueError(f"unregistered node event kind {kind!r}; add it to NODE_EVENTS and the ICD")
    return ".".join(["node", token(node_id), kind, *map(token, detail)])


def local_all(node_id: str) -> str:
    return f"node.{token(node_id)}.>"


def cdm_accepted(node_id: str, event_id: str) -> str:
    return local(node_id, "cdm.accepted", event_id)


def cdm_rejected(node_id: str) -> str:
    return local(node_id, "cdm.rejected")


def sync_manifest(hub_id: str) -> str:
    return f"sync.{token(hub_id)}.manifest"


def sync_fetch(hub_id: str) -> str:
    return f"sync.{token(hub_id)}.fetch"


def ops_exchange(hub_id: str) -> str:
    return f"ops.{token(hub_id)}.exchange"
