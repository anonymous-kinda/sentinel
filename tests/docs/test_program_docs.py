"""The program documents name only commands that exist and state only
numbers the repository generated.

The documents are the white paper, the quad chart, the demo script and the
install guide. Each check is first shown to catch a deliberately wrong input,
then run against the real documents.
"""

import pytest

from .doccheck import (
    DOCS,
    PROGRAM_DOCS,
    QUAD_CHART_SVG,
    broken_links,
    cli_problems,
    code_snippets,
    missing_make_targets,
    missing_references,
    proof_point_problems,
    section,
    stated_numbers,
    svg_text,
    win_theme_problems,
)

WHITE_PAPER = DOCS / "white-paper.md"

# Products that belong in these public documents only as integration targets,
# and are better left out of them entirely.
THIRD_PARTY_PRODUCTS = ("Privateer", "Wayfinder", "Crow's Nest")


def all_snippets() -> list[str]:
    """Every piece of code in the documents, plus the quad chart's text."""
    snippets = [s for doc in PROGRAM_DOCS for s in code_snippets(doc.read_text())]
    return [*snippets, svg_text(QUAD_CHART_SVG)]


# --------------------------------------------------------- the checks catch it


def test_numbers_are_quantities_not_identifiers():
    assert stated_numbers("53 events, 64,058 bytes, 1.5e-08, 6.9x sooner, $17.50") == [
        "53", "64,058", "1.5e-08", "6.9", "17.50",
    ]
    assert stated_numbers("ADR-007, x86_64, CCSDS 508.0-B-1, SysML v2, 2026-09-24, §4401, p95") == []


def test_an_unknown_make_target_or_variable_is_named():
    assert missing_make_targets(["make no-such-target"]) == ["target no-such-target"]
    assert missing_make_targets(["make screen PRIMAY=41599"]) == ["variable PRIMAY"]
    assert missing_make_targets(["make screen PRIMARY=41599 && make airgap-selftest"]) == []


def test_a_missing_script_path_or_test_is_named():
    snippets = [
        "deploy/bundle/no_such.sh artifact",
        "COSIGN=./cosign unshare -rn ./no_such_either.sh bundle.tar.gz",
        "tests/test_cdm_codec.py::test_that_does_not_exist",
        "python -m harness.no_such_module",
    ]
    assert missing_references(snippets) == [
        "deploy/bundle/no_such.sh",
        "deploy/bundle/no_such_either.sh",
        "tests/test_cdm_codec.py::test_that_does_not_exist",
        "harness/no_such_module.py",
    ]
    real = ["./verify_signature.sh x", "tests/test_cdm_codec.py::test_every_nasa_cdm_parses_and_round_trips"]
    assert missing_references(real) == []


def test_a_broken_link_is_named():
    markdown = "[ok](validation-report.md#5-x) [gone](no-such-report.md) [web](https://example.org)"
    assert broken_links(markdown, DOCS) == ["no-such-report.md"]


def test_a_command_the_real_cli_rejects_is_named():
    assert cli_problems(["uv run sentinel screen --primry 41599"]) == [
        "sentinel screen --primry 41599"
    ]
    assert cli_problems(["SENTINEL_DB=:memory: ./venv/bin/sentinel serve --port 18799"]) == []


def test_a_proof_point_number_its_report_does_not_state_is_caught():
    wrong = "| W2 | Most urgent record in 38.3 s. | [DDIL](ddil-results.md#limited) |"
    assert proof_point_problems(wrong) == ["W2: 38.3 is not in ddil-results.md"]
    elsewhere = "| W3 | Right tool 0.460 of the time. | [DDIL](ddil-results.md) |"
    assert proof_point_problems(elsewhere) == ["W3: 0.460 is not in ddil-results.md"]
    unlinked = "| W1 | 53 events. | `tests/test_tier3_cara_validation.py` |"
    assert proof_point_problems(unlinked) == ["W1: states 53 but links no generated report"]
    right = "| W2 | 5.5 s against 38.2 s. | [DDIL](ddil-results.md#limited) |"
    assert proof_point_problems(right) == []


def test_a_long_or_unsupported_win_theme_is_caught():
    themes = (
        "- **W1. Short.** Backed.\n"
        "- **W2. Long.** " + "word " * 25 + "\n"
    )
    proofs = "| W1 | A claim. | `tests/test_cdm_codec.py` |\n"
    assert win_theme_problems(themes, proofs) == [
        "W2 has 26 words (at most 25)",
        "W2 has no proof point with evidence",
    ]


# ------------------------------------------------------ the real documents


def test_every_program_document_exists():
    assert [doc.name for doc in PROGRAM_DOCS if not doc.is_file()] == []
    assert QUAD_CHART_SVG.is_file()


def test_every_make_target_and_variable_named_exists():
    assert missing_make_targets(all_snippets()) == []


def test_every_script_file_and_test_named_exists():
    assert missing_references(all_snippets()) == []


def test_every_link_resolves():
    assert {doc.name: broken_links(doc.read_text(), doc.parent) for doc in PROGRAM_DOCS} == {
        doc.name: [] for doc in PROGRAM_DOCS
    }


def test_every_sentinel_command_parses_with_the_real_cli():
    assert cli_problems(all_snippets()) == []


def test_every_proof_point_number_is_in_the_generated_report_it_links():
    proofs = section(WHITE_PAPER.read_text(), "Proof points")
    assert proof_point_problems(proofs) == []


def test_every_win_theme_is_short_and_backed_by_a_proof_point():
    text = WHITE_PAPER.read_text()
    themes, proofs = section(text, "Win themes"), section(text, "Proof points")
    assert themes.count("- **W") >= 3
    assert win_theme_problems(themes, proofs) == []


@pytest.mark.parametrize("name", THIRD_PARTY_PRODUCTS)
def test_no_third_party_product_is_named(name):
    documents = [*PROGRAM_DOCS, QUAD_CHART_SVG]
    assert [doc.name for doc in documents if name.lower() in doc.read_text().lower()] == []
