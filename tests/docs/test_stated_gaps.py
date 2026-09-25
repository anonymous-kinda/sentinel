"""A gap the docs state stays stated, the same way everywhere it appears.

- The unsigned-annotation gap (SECURITY.md gap 4) has one fix order: mutual
  TLS on the leaf link first, which keeps unenrolled peers off the exchange,
  then signed registers, which stop an enrolled edge overwriting a register it
  did not write. SECURITY.md and the system design must name both, in that
  order.
- The compose stack has never run in a container. Every document that offers
  it says so. Delete that check, and the sentences, after the first real run.

Each check is first shown to catch a deliberately wrong input, then run
against the real documents.
"""

import re

import pytest

from .doccheck import DOCS, ROOT

ANNOTATION_FIXES_IN_ORDER = ("mutual TLS", "signed registers")
NOT_RUN = re.compile(r"\bha(?:s|ve) not (?:yet )?run\b")
COMPOSE_DOCS = ["README.md", "docs/compose.md", "CHANGELOG.md"]


def names_in_order(text: str, phrases: tuple[str, ...]) -> bool:
    positions = [text.find(phrase) for phrase in phrases]
    return -1 not in positions and positions == sorted(positions)


def security_gap_4() -> str:
    text = (ROOT / "SECURITY.md").read_text()
    match = re.search(
        r"^4\. \*\*Annotations are not signed.*?(?=^\S|\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match, "SECURITY.md has no gap 4 on unsigned annotations"
    return " ".join(match[0].split())


def system_design_gap() -> str:
    text = (DOCS / "system-design.md").read_text()
    match = re.search(r"^\*\*Gap, stated: annotations are not signed\.\*\*.*$", text, re.MULTILINE)
    assert match, "system-design.md has no stated annotation gap"
    return match[0]


def test_the_order_check_catches_a_reversed_or_missing_fix():
    assert names_in_order("first mutual TLS, then signed registers", ANNOTATION_FIXES_IN_ORDER)
    assert not names_in_order("signed registers, or mutual TLS", ANNOTATION_FIXES_IN_ORDER)
    assert not names_in_order(
        "sign the registers, or authenticate peers", ANNOTATION_FIXES_IN_ORDER
    )


@pytest.mark.parametrize(
    "statement", [security_gap_4, system_design_gap], ids=["SECURITY.md", "system-design.md"]
)
def test_the_annotation_gap_names_its_fixes_in_order(statement):
    assert names_in_order(statement(), ANNOTATION_FIXES_IN_ORDER)


def test_the_disclosure_check_catches_a_doc_without_one():
    assert NOT_RUN.search("The containers have not run yet.")
    assert NOT_RUN.search("It has not yet run in a container.")
    assert not NOT_RUN.search("CI runs the whole stack on every push.")


@pytest.mark.parametrize("doc", COMPOSE_DOCS)
def test_every_doc_offering_the_compose_stack_says_it_has_not_run(doc):
    assert NOT_RUN.search((ROOT / doc).read_text())
