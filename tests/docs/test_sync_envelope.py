"""docs/icd/sync-envelope.md against sentinel/sync, sentinel/triage and the
modules that plug into them.

The generic summary fields are the ones the agent actually reads; the
priority classes and consequence levels are the enums' own members; the
verification and queue states are the constants the code assigns; the
headers are the ones sync and the ReferenceRecords implementations set or
read; the protocol's methods are the protocol's. All compared both ways.
"""

import inspect

from sentinel.api.app import SYNC_ELEMENT_SCOPES
from sentinel.conjunction.summaries import SUMMARY_MAX_BYTES
from sentinel.passes.sync_adapter import PREFIX as ELEMENT_PREFIX
from sentinel.sync.records import ReferenceRecords
from sentinel.triage import Consequence, PriorityClass

from .icd import (
    ICD,
    assigned_constants,
    backticked,
    column,
    compare,
    dict_keys,
    dict_values_for,
    drop_row,
    function,
    headers_read,
    keys_read,
    returned_constants,
    string_constants,
    table_rows,
    tree,
    trees,
)

ENVELOPE = ICD / "sync-envelope.md"
HEADER = r"(Sentinel|Nats)-[A-Za-z0-9]+(-[A-Za-z0-9]+)*"
SYNC = trees("sentinel/sync/*.py")
RECORDS = trees("sentinel/conjunction/sync_adapter.py", "sentinel/passes/sync_adapter.py")
SUMMARIES = tree("sentinel/conjunction/summaries.py")
SERVICE = tree("sentinel/conjunction/service.py")
ELEMENTS = tree("sentinel/passes/sync_adapter.py")


def generic_fields() -> set[str]:
    return keys_read(SYNC, "compact")


def conjunction_fields() -> set[str]:
    return dict_keys(function(SUMMARIES, "compact_summary")) - generic_fields()


def element_fields() -> set[str]:
    return dict_keys(function(ELEMENTS, "manifest"))


def verification_states() -> set[str]:
    return returned_constants(function(SERVICE, "_verification")) | dict_values_for([SUMMARIES], "verification")


def queue_states() -> set[str]:
    return assigned_constants(SYNC, "status")


def sync_headers() -> set[str]:
    return string_constants(SYNC + RECORDS, HEADER) | headers_read(SYNC)


def protocol_methods() -> set[str]:
    return {name for name, _ in inspect.getmembers(ReferenceRecords, inspect.isfunction) if not name.startswith("_")}


def members(enum) -> set[tuple[str, int]]:
    return {(member.name, int(member)) for member in enum}


def documented_members(doc: str, heading: str) -> set[tuple[str, int]]:
    return {(backticked(name)[0], int(value)) for name, value, *_ in table_rows(doc, heading)}


def documented_methods(doc: str) -> set[str]:
    return {token.split("(")[0] for token in column(doc, "ReferenceRecords")}


def envelope_problems(doc: str) -> list[str]:
    problems = compare(column(doc, "Fields sync reads"), generic_fields(), "generic summary field")
    problems += compare(column(doc, "Conjunction summary"), conjunction_fields(), "conjunction summary field")
    problems += compare(documented_members(doc, "Priority classes"), members(PriorityClass), "priority class")
    problems += compare(documented_members(doc, "Consequence"), members(Consequence), "consequence")
    problems += compare(column(doc, "Verification states"), verification_states(), "verification state")
    problems += compare(column(doc, "Queue states"), queue_states(), "queue state")
    problems += compare(column(doc, "Headers"), sync_headers(), "header")
    problems += compare(documented_methods(doc), protocol_methods(), "ReferenceRecords method")
    problems += compare(column(doc, "Item-id prefixes"), {ELEMENT_PREFIX}, "item-id prefix")
    problems += compare(column(doc, "Element sets offered"), set(SYNC_ELEMENT_SCOPES), "element-set scope")
    if element_fields() != generic_fields():
        problems.append("an element-set summary no longer carries exactly the four generic fields")
    if f"{SUMMARY_MAX_BYTES} bytes" not in doc:
        problems.append(f"the {SUMMARY_MAX_BYTES}-byte summary limit is not stated")
    return problems


def test_the_source_yields_what_sync_is_known_to_use():
    assert generic_fields() == {"e", "dl", "q", "c"}
    assert {"h", "dc", "pc"} <= conjunction_fields()
    assert {"HUB_ASSERTED", "VERIFIED", "MISMATCH"} <= verification_states()
    assert {"QUEUED", "SUMMARY_ONLY"} <= queue_states()
    assert {"Sentinel-Event-Id", "Sentinel-Sha256", "Sentinel-Digest"} <= sync_headers()
    assert "ingest" in protocol_methods()
    assert element_fields() == {"e", "dl", "q", "c"}


def test_the_envelope_matches_the_code():
    assert envelope_problems(ENVELOPE.read_text()) == []


def test_a_stale_envelope_is_caught():
    doc = ENVELOPE.read_text()
    assert envelope_problems(drop_row(doc, "dl")) == ["generic summary field dl is not documented"]
    assert envelope_problems(drop_row(doc, "P3_REFERENCE")) == ["priority class ('P3_REFERENCE', 3) is not documented"]
    assert envelope_problems(drop_row(doc, "MISMATCH")) == ["verification state MISMATCH is not documented"]
    assert envelope_problems(drop_row(doc, "Sentinel-Sha256")) == ["header Sentinel-Sha256 is not documented"]
    renumbered = doc.replace("| `WATCH` | 1 |", "| `WATCH` | 4 |", 1)
    assert envelope_problems(renumbered) == [
        "consequence ('WATCH', 1) is not documented",
        "consequence ('WATCH', 4) is documented but not in the code",
    ]
