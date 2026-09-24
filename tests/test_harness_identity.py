"""Node identities and the trust file, as a two-node deployment provisions them.

A node signs its operator data with an Ed25519 key kept in its own var dir,
and merges another node's entries only if the trust file names that node's
public key. The process harness and the Compose stack both enrol every node
into one trust file before any node starts (harness/identity.py). Without
it the hub rejects the edge's signed entries and the two never converge.
"""

import json

from harness.identity import enroll, main
from sentinel.crdt.signing import TrustStore
from sentinel.ops.service import load_identity


def test_enrolment_creates_the_key_exactly_where_the_node_loads_it(tmp_path):
    public = enroll("hub", tmp_path / "hub", tmp_path / "trust.json")
    key, _ = load_identity("hub", tmp_path / "hub", None)
    assert key.public_hex() == public


def test_two_enrolments_leave_both_nodes_in_one_trust_file(tmp_path):
    trust = tmp_path / "trust" / "trust.json"
    hub = enroll("hub", tmp_path / "hub", trust)
    edge = enroll("edge-alpha", tmp_path / "edge", trust)
    assert json.loads(trust.read_text()) == {"edge-alpha": edge, "hub": hub}
    store = TrustStore.from_file(trust)
    assert store.trusts("hub") and store.trusts("edge-alpha")


def test_enrolling_again_keeps_the_key_and_the_trust_file(tmp_path):
    trust = tmp_path / "trust.json"
    first = enroll("hub", tmp_path / "hub", trust)
    before = trust.read_bytes()
    assert enroll("hub", tmp_path / "hub", trust) == first
    assert trust.read_bytes() == before


def test_a_node_var_dir_holds_only_its_own_private_key(tmp_path):
    trust = tmp_path / "trust.json"
    enroll("hub", tmp_path / "hub", trust)
    enroll("edge-alpha", tmp_path / "edge", trust)
    assert sorted(p.name for p in (tmp_path / "hub").rglob("*.pem")) == ["hub.ed25519.pem"]
    assert sorted(p.name for p in (tmp_path / "edge").rglob("*.pem")) == ["edge-alpha.ed25519.pem"]
    assert "PRIVATE" not in trust.read_text()


def test_the_command_line_enrols_one_node(tmp_path):
    trust = tmp_path / "trust.json"
    assert main(["edge-alpha", str(tmp_path / "edge"), str(trust)]) == 0
    assert list(json.loads(trust.read_text())) == ["edge-alpha"]
