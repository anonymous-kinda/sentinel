"""Ed25519 node keys and the trust store that decides whose entries count.

Every decision-log entry is signed by the node that authored it. A replica
merges only entries whose signature verifies under a key in its trust store:
the keys in the JSON file SENTINEL_TRUST_FILE names, plus the node's own
(sentinel.ops.service.load_identity); without that file, only its own.
Validity is a deterministic function of the entry and the trust store, so
filtering before the union keeps merge a join (see log.py).
"""

from __future__ import annotations

import json
import pathlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class NodeKey:
    def __init__(self, node_id: str, private: Ed25519PrivateKey):
        self.node_id = node_id
        self._private = private

    @classmethod
    def generate(cls, node_id: str) -> NodeKey:
        return cls(node_id, Ed25519PrivateKey.generate())

    @classmethod
    def load_or_create(cls, node_id: str, path: pathlib.Path) -> NodeKey:
        if path.exists():
            private = serialization.load_pem_private_key(path.read_bytes(), password=None)
            assert isinstance(private, Ed25519PrivateKey)
            return cls(node_id, private)
        key = cls.generate(node_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            key._private.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        path.chmod(0o600)
        return key

    def sign(self, message: bytes) -> bytes:
        return self._private.sign(message)

    def public_hex(self) -> str:
        raw = self._private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return raw.hex()


class TrustStore:
    """node_id -> Ed25519 public key, read from a JSON map of node id to hex
    key (`from_file`). Neither versioned nor hashed: nothing records which
    trust store a merge ran under."""

    def __init__(self, keys: dict[str, str] | None = None):
        self._keys: dict[str, Ed25519PublicKey] = {}
        self._hex: dict[str, str] = {}
        for node, hex_key in (keys or {}).items():
            self.add(node, hex_key)

    def add(self, node_id: str, public_hex: str) -> None:
        self._keys[node_id] = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))
        self._hex[node_id] = public_hex

    def trusts(self, node_id: str) -> bool:
        return node_id in self._keys

    def verify(self, node_id: str, message: bytes, signature: bytes) -> bool:
        key = self._keys.get(node_id)
        if key is None:
            return False
        try:
            key.verify(signature, message)
            return True
        except InvalidSignature:
            return False

    def to_json(self) -> str:
        return json.dumps(dict(sorted(self._hex.items())), indent=1)

    @classmethod
    def from_file(cls, path: pathlib.Path) -> TrustStore:
        return cls(json.loads(path.read_text())) if path.exists() else cls()
