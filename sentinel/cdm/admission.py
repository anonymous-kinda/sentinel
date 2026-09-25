"""Admission: raw bytes to a CDM and its Conjunction, or the code that quarantines them.

The node's ingest and the command line read CDMs through this one path, so
the CLI never assesses, or calls clean, a message the node would quarantine,
and both give the same code and reason:

    bytes --read----> not UTF-8?              -> CdmRejected UNREADABLE
                      not a KVN CDM?          -> CdmRejected PARSE_ERROR
          --convert-> wrong?                  -> CdmRejected with the validator's code
                      a value not readable?   -> CdmRejected UNREADABLE
"""

from __future__ import annotations

from typing import NamedTuple

from .kvn import CdmParseError, parse_bytes
from .model import CdmMessage
from .to_conjunction import Conversion, to_conjunction
from .validate import CdmRejected


class Admitted(NamedTuple):
    message: CdmMessage
    conversion: Conversion


def read_message(raw: bytes) -> CdmMessage:
    """The message's structure, without judging its values. Raises
    CdmRejected: UNREADABLE for bytes that are not UTF-8, PARSE_ERROR for
    text that is not a KVN CDM."""
    try:
        return parse_bytes(raw)
    except UnicodeDecodeError as exc:
        raise CdmRejected("UNREADABLE", str(exc)) from exc
    except CdmParseError as exc:
        raise CdmRejected("PARSE_ERROR", str(exc)) from exc


def admit(raw: bytes, hbr_override_m: float | None = None) -> Admitted:
    """Read, validate and convert, as the node admits a CDM. Raises
    CdmRejected with the code the node quarantines the message under."""
    message = read_message(raw)
    try:
        return Admitted(message, to_conjunction(message, hbr_override_m))
    except CdmRejected:
        raise
    except (ValueError, KeyError) as exc:
        raise CdmRejected("UNREADABLE", str(exc)) from exc
