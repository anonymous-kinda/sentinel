"""Enrol a node: create (or load) its signing key, and add its public key to
the trust file every node of the deployment reads at start.

    uv run python harness/identity.py <node_id> <var_dir> <trust_file>

The key is made by `sentinel.ops.service.load_identity`, the call the node
itself makes at start, so it lands exactly where the node will look. The
private key never leaves `var_dir`; the trust file holds public keys only.
Enrolling again is a no-op, so a deployment can run this on every start.

Used by the process harness (cluster.py) and by the Compose stack, where
each node's enrolment is a one-shot container that sees only that node's
state (deploy/compose/compose.yaml). Runs as a script there, so it
imports nothing from the harness package.
"""

from __future__ import annotations

import os
import pathlib
import sys

from sentinel.crdt.signing import TrustStore
from sentinel.obs import configure_logging, get_logger
from sentinel.ops.service import load_identity

log = get_logger(__name__)


def enroll(node_id: str, var_dir: pathlib.Path, trust_file: pathlib.Path) -> str:
    """The node's public key (hex), now also in `trust_file`."""
    key, _ = load_identity(node_id, pathlib.Path(var_dir), None)
    public = key.public_hex()
    trust = TrustStore.from_file(trust_file)
    trust.add(node_id, public)
    _write_atomically(pathlib.Path(trust_file), trust.to_json() + "\n")
    log.info("Node enrolled", node_id=node_id, trust_file=str(trust_file))
    return public


def _write_atomically(path: pathlib.Path, text: str) -> None:
    """A reader never sees a half-written trust file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(text)
    os.replace(partial, path)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    configure_logging()
    node_id, var_dir, trust_file = args
    enroll(node_id, pathlib.Path(var_dir), pathlib.Path(trust_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
