"""Keyword = Value Notation (KVN) codec for CDMs.

Structure, per CCSDS 508.0-B-1: a header and relative-metadata block, then
two object blocks each introduced by ``OBJECT = OBJECT1`` / ``OBJECT2``.
COMMENT lines may appear anywhere and are kept in place.

Parsing is structural only. Whether the numbers make physical sense is
validate.py's job, so that a malformed-but-readable message can still be
quarantined with a precise reason rather than failing to load at all.
"""

from __future__ import annotations

import re

from .model import CdmMessage, CdmSection, Comment, Entry, KvnField

_KV = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*)\s*=\s*(?P<rest>.*?)\s*$")
_UNIT = re.compile(r"^(?P<value>.*?)\s*\[(?P<unit>[^\]]*)\]\s*$")


class CdmParseError(ValueError):
    """The text is not structurally a KVN CDM."""


def _parse_line(line: str, lineno: int) -> Entry | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("COMMENT"):
        # "COMMENT" followed by free text; keep the text exactly.
        return Comment(stripped[len("COMMENT"):].lstrip())
    m = _KV.match(stripped)
    if not m:
        raise CdmParseError(f"line {lineno}: not a KVN line: {stripped!r}")
    rest = m["rest"]
    unit_match = _UNIT.match(rest)
    if unit_match:
        return KvnField(m["key"], unit_match["value"].strip(), unit_match["unit"].strip())
    return KvnField(m["key"], rest.strip(), None)


def parse(text: str) -> CdmMessage:
    """Parse KVN text into a CdmMessage. Raises CdmParseError on structure."""
    preamble: list[Entry] = []
    objects: list[list[Entry]] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        entry = _parse_line(line, lineno)
        if entry is None:
            continue
        if isinstance(entry, KvnField) and entry.key == "OBJECT":
            expected = f"OBJECT{len(objects) + 1}"
            if entry.value != expected:
                raise CdmParseError(
                    f"line {lineno}: expected OBJECT = {expected}, got {entry.value!r}"
                )
            objects.append([entry])
            continue
        (objects[-1] if objects else preamble).append(entry)

    if len(objects) != 2:
        raise CdmParseError(f"a CDM has exactly two object blocks; found {len(objects)}")
    if not any(isinstance(e, KvnField) and e.key == "CCSDS_CDM_VERS" for e in preamble):
        raise CdmParseError("missing CCSDS_CDM_VERS; this is not a CDM")

    return CdmMessage(
        preamble=CdmSection(tuple(preamble)),
        objects=(CdmSection(tuple(objects[0])), CdmSection(tuple(objects[1]))),
    )


def parse_bytes(data: bytes) -> CdmMessage:
    """Parse raw bytes (UTF-8 or ASCII, optional BOM)."""
    return parse(data.decode("utf-8-sig"))


def _emit_section(section: CdmSection, width: int) -> list[str]:
    out = []
    for entry in section.entries:
        if isinstance(entry, Comment):
            out.append(f"COMMENT {entry.text}".rstrip())
        else:
            line = f"{entry.key:<{width}} = {entry.value}"
            if entry.unit is not None:
                line = f"{line:<{width + 30}} [{entry.unit}]"
            out.append(line)
    return out


def emit(message: CdmMessage) -> str:
    """Serialise to KVN. parse(emit(m)) == m for any parsed message."""
    width = max(
        (len(f.key) for s in (message.preamble, *message.objects) for f in s.fields()),
        default=0,
    )
    lines = _emit_section(message.preamble, width)
    for obj in message.objects:
        lines.extend(_emit_section(obj, width))
    return "\n".join(lines) + "\n"
