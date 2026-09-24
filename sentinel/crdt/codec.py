"""Canonical CBOR (RFC 8949 s4.2): the bytes that get signed and hashed.

Canonical encoding makes the signature a property of the content, not of
the dictionary order some implementation happened to use.
"""

from __future__ import annotations

import hashlib
from typing import Any

import cbor2


def encode(value: object) -> bytes:
    return cbor2.dumps(value, canonical=True)


def decode(data: bytes) -> Any:
    """Whatever the bytes hold. Wire data: the caller states the shape it expects."""
    return cbor2.loads(data)


def digest(value: object) -> str:
    return hashlib.sha256(encode(value)).hexdigest()
