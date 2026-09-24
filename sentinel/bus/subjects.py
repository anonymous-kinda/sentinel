"""Subject namespace. One place, so the ICD (docs/icd/asyncapi.yaml) can be
checked against it.

    cdm.accepted.<event_id>     a CDM was admitted and assessed
    cdm.rejected                a CDM was quarantined (wrong input)
    ops.delta.<node_id>         CRDT deltas authored at a node (M2)
    passes.window.<unit_id>     pass windows for a ground unit (M3; edge only)
    unit.>                      ground-unit data (never leaves the edge)
"""

CDM_ACCEPTED = "cdm.accepted.{event_id}"
CDM_ACCEPTED_ALL = "cdm.accepted.>"
CDM_REJECTED = "cdm.rejected"


def token(value: str) -> str:
    """Make a value safe as a single subject token."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value) or "_"
