"""docs/icd/sync-envelope.md against sentinel/sync, sentinel/triage and the
modules that plug into them.

The generic summary fields are the ones the agent actually reads; the
priority classes and consequence levels are the enums' own members; the
verification and queue states are the constants the code assigns; the
headers are the ones sync and the ReferenceRecords implementations set or
read; the protocol's methods are the protocol's. All compared both ways.

The modules are discovered, not listed. Every class under sentinel/ that
defines the protocol's methods is an implementation whose headers are
checked, and every item-id prefix the node's assembly gives
CompositeRecords is one the document must list. A third mission module is
checked the day it lands, without this file changing.
"""

import ast
import inspect
import textwrap

from sentinel.api.app import SYNC_ELEMENT_SCOPES
from sentinel.api.records import CompositeRecords
from sentinel.conjunction.summaries import SUMMARY_MAX_BYTES
from sentinel.passes.sync_adapter import PREFIX as ELEMENT_PREFIX
from sentinel.passes.sync_adapter import ElementRecords
from sentinel.sync.records import ReferenceRecords
from sentinel.triage import Consequence, PriorityClass

from .icd import (
    ICD,
    Found,
    Source,
    assigned_constants,
    backticked,
    classes_implementing,
    column,
    compare,
    dict_keys,
    dict_values_for,
    drop_row,
    function,
    headers_read,
    keys_read,
    mapping_keys,
    returned_constants,
    sources,
    string_constants,
    table_rows,
    tree,
    trees,
)

ENVELOPE = ICD / "sync-envelope.md"
HEADER = r"(Sentinel|Nats)-[A-Za-z0-9]+(-[A-Za-z0-9]+)*"
SENTINEL = sources("sentinel/**/*.py")
SYNC = trees("sentinel/sync/*.py")
SUMMARIES = tree("sentinel/conjunction/summaries.py")
SERVICE = tree("sentinel/conjunction/service.py")


def protocol_methods() -> set[str]:
    return {name for name, _ in inspect.getmembers(ReferenceRecords, inspect.isfunction) if not name.startswith("_")}


def record_classes(scanned: list[Source] = SENTINEL) -> list[ast.ClassDef]:
    """Every ReferenceRecords implementation: each class defining all the protocol's methods."""
    return classes_implementing(scanned, protocol_methods())


def item_prefixes(scanned: list[Source] = SENTINEL) -> Found:
    """The item-id prefixes given to CompositeRecords, wherever it is assembled."""
    return mapping_keys(scanned, CompositeRecords.__name__, 1, "by_prefix")


def generic_fields() -> set[str]:
    return keys_read(SYNC, "compact")


def conjunction_fields() -> set[str]:
    return dict_keys(function(SUMMARIES, "compact_summary")) - generic_fields()


def element_fields() -> set[str]:
    """What an element-set summary carries: the document says only the generic four."""
    return dict_keys(function(ast.parse(textwrap.dedent(inspect.getsource(ElementRecords))), "manifest"))


def verification_states() -> set[str]:
    return returned_constants(function(SERVICE, "_verification")) | dict_values_for([SUMMARIES], "verification")


def queue_states() -> set[str]:
    return assigned_constants(SYNC, "status")


def sync_headers(scanned: list[Source] = SENTINEL) -> set[str]:
    return string_constants(SYNC + record_classes(scanned), HEADER) | headers_read(SYNC)


def members(enum) -> set[tuple[str, int]]:
    return {(member.name, int(member)) for member in enum}


def documented_members(doc: str, heading: str) -> set[tuple[str, int]]:
    return {(backticked(name)[0], int(value)) for name, value, *_ in table_rows(doc, heading)}


def documented_methods(doc: str) -> set[str]:
    return {token.split("(")[0] for token in column(doc, "ReferenceRecords")}


def envelope_problems(doc: str, scanned: list[Source] = SENTINEL) -> list[str]:
    prefixes = item_prefixes(scanned)
    problems = compare(column(doc, "Fields sync reads"), generic_fields(), "generic summary field")
    problems += compare(column(doc, "Conjunction summary"), conjunction_fields(), "conjunction summary field")
    problems += compare(documented_members(doc, "Priority classes"), members(PriorityClass), "priority class")
    problems += compare(documented_members(doc, "Consequence"), members(Consequence), "consequence")
    problems += compare(column(doc, "Verification states"), verification_states(), "verification state")
    problems += compare(column(doc, "Queue states"), queue_states(), "queue state")
    problems += compare(column(doc, "Headers"), sync_headers(scanned), "header")
    problems += compare(documented_methods(doc), protocol_methods(), "ReferenceRecords method")
    problems += compare(column(doc, "Item-id prefixes"), prefixes.values, "item-id prefix")
    problems += [f"a CompositeRecords prefix at {where} cannot be read by this check" for where in prefixes.unresolved]
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
    assert {"ConjunctionRecords", "ElementRecords", "CompositeRecords"} <= {cls.name for cls in record_classes()}
    assert item_prefixes() == Found({ELEMENT_PREFIX}, [])


def test_the_envelope_matches_the_code():
    assert envelope_problems(ENVELOPE.read_text()) == []


# A third mission module, as it would land: an adapter with its own prefix
# and header, assembled in the node beside the others.
PLANTED = {
    "sentinel/survey/sync_adapter.py": '''
PREFIX = "svy:"


class SurveyRecords:
    def manifest(self):
        return []

    def get(self, sha16):
        return b"", {"Sentinel-Sha256": sha16, "Sentinel-Survey-Epoch": "2026-09-24"}

    def has(self, sha16):
        return False

    def put_summaries(self, summaries, origin):
        pass

    async def ingest(self, raw, source, data_class, item_id):
        return {"status": "accepted", "sha256": "", "verification": None}


class NotRecords:
    def manifest(self):
        return []
''',
    "sentinel/survey/node.py": '''
from ..api.records import CompositeRecords
from .sync_adapter import PREFIX as SURVEY_PREFIX


def assemble(default, survey):
    return CompositeRecords(default, {SURVEY_PREFIX: survey})


def assemble_from(default, table):
    return CompositeRecords(default, by_prefix=table)
''',
}


def plant(root) -> list[Source]:
    for relative, text in PLANTED.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return sources("sentinel/**/*.py", root=root)


def test_a_third_mission_module_is_checked_without_being_named(tmp_path):
    planted = plant(tmp_path)
    assert [cls.name for cls in record_classes(planted)] == ["SurveyRecords"]
    assert item_prefixes(planted) == Found({"svy:"}, ["sentinel/survey/node.py:11"])
    assert envelope_problems(ENVELOPE.read_text(), SENTINEL + planted) == [
        "header Sentinel-Survey-Epoch is not documented",
        "item-id prefix svy: is not documented",
        "a CompositeRecords prefix at sentinel/survey/node.py:11 cannot be read by this check",
    ]


def test_a_stale_envelope_is_caught():
    doc = ENVELOPE.read_text()
    assert envelope_problems(drop_row(doc, "dl")) == ["generic summary field dl is not documented"]
    assert envelope_problems(drop_row(doc, "P3_REFERENCE")) == ["priority class ('P3_REFERENCE', 3) is not documented"]
    assert envelope_problems(drop_row(doc, "MISMATCH")) == ["verification state MISMATCH is not documented"]
    assert envelope_problems(drop_row(doc, "Sentinel-Sha256")) == ["header Sentinel-Sha256 is not documented"]
    assert envelope_problems(drop_row(doc, "omm:")) == ["item-id prefix omm: is not documented"]
    renumbered = doc.replace("| `WATCH` | 1 |", "| `WATCH` | 4 |", 1)
    assert envelope_problems(renumbered) == [
        "consequence ('WATCH', 1) is not documented",
        "consequence ('WATCH', 4) is documented but not in the code",
    ]
