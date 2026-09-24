"""Subject namespace. One place, so the ICD (docs/icd/asyncapi.yaml) can be
checked against it.

Node-local (never cross a leaf link - each node subscribes only to its own):

    node.<node_id>.cdm.accepted.<event>   a CDM was admitted and assessed
    node.<node_id>.cdm.rejected           a CDM was quarantined
    node.<node_id>.ops.changed            operator data changed (CRDT merge)
    node.<node_id>.sync.progress          sync agent state (edge)
    node.<node_id>.link.state             measured link state changed

Cross-node, request/reply, served by the hub:

    sync.<hub_id>.manifest                event summaries (P0)
    sync.<hub_id>.fetch                   one CDM, original KVN bytes
    ops.<hub_id>.exchange                 CRDT anti-entropy, both directions

Never exported across a leaf (enforced by leafnode permissions, M3):

    unit.>, passes.>                      ground-unit position and pass windows
"""


def token(value: str) -> str:
    """Make a value safe as a single subject token."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value) or "_"


def local(node_id: str, suffix: str) -> str:
    return f"node.{token(node_id)}.{suffix}"


def local_all(node_id: str) -> str:
    return f"node.{token(node_id)}.>"


def cdm_accepted(node_id: str, event_id: str) -> str:
    return local(node_id, f"cdm.accepted.{token(event_id)}")


def cdm_rejected(node_id: str) -> str:
    return local(node_id, "cdm.rejected")


def sync_manifest(hub_id: str) -> str:
    return f"sync.{token(hub_id)}.manifest"


def sync_fetch(hub_id: str) -> str:
    return f"sync.{token(hub_id)}.fetch"


def ops_exchange(hub_id: str) -> str:
    return f"ops.{token(hub_id)}.exchange"
