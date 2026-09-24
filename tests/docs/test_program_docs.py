"""The program documents name only commands that exist and state only
numbers the repository generated.

The documents are the white paper, the quad chart, the demo script and the
install guide. tests/test_docs.py already guards every Markdown page's paths,
links, make targets and CLI subcommands; these tests apply the same rules to
the program documents (the quad chart's SVG included) and add what those
rules do not cover. Each check is first shown to catch a deliberately wrong
input, then run against the real documents.
"""

import pytest

from tests.doclint import parse_markdown

from .doccheck import (
    DOCS,
    PROGRAM_DOCS,
    QUAD_CHART_SVG,
    cli_problems,
    document,
    missing_make_targets,
    missing_references,
    proof_point_problems,
    section,
    win_theme_problems,
)

WHITE_PAPER = DOCS / "white-paper.md"
ALL_DOCUMENTS = (*PROGRAM_DOCS, QUAD_CHART_SVG)

# Products that belong in public documents only as integration targets, and
# are better left out of these ones entirely.
THIRD_PARTY_PRODUCTS = ("Privateer", "Wayfinder", "Crow's Nest")


def _name(path) -> str:
    return path.name


# --------------------------------------------------------- the checks catch it


def test_an_unknown_make_target_or_variable_is_named():
    md = parse_markdown("`make no-such-target`\n```\nmake screen PRIMAY=41599 && make airgap-selftest\n```\n")
    assert missing_make_targets(md) == ["no-such-target", "PRIMAY="]
    assert missing_make_targets(parse_markdown("`make screen PRIMARY=41599 HOURS=24`")) == []


def test_a_missing_script_path_or_test_is_named():
    md = parse_markdown(
        "`deploy/bundle/no_such.sh artifact`\n"
        "```\nCOSIGN=./cosign unshare -rn ./no_such_either.sh bundle.tar.gz\n```\n"
        "`tests/test_cdm_codec.py::test_that_does_not_exist` and [gone](no-such-report.md)"
    )
    assert missing_references(md, DOCS) == [
        "deploy/bundle/no_such.sh",
        "no-such-report.md",
        "deploy/bundle/no_such_either.sh",
        "tests/test_cdm_codec.py::test_that_does_not_exist",
    ]
    real = parse_markdown(
        "`./verify_signature.sh x` `tests/test_cdm_codec.py::test_every_nasa_cdm_parses_and_round_trips` "
        "[report](validation-report.md#5-x)"
    )
    assert missing_references(real, DOCS) == []


def test_a_command_the_real_cli_rejects_is_named():
    wrong = parse_markdown("`uv run sentinel screen --primry 41599`\n\n`sentinel screen --primary NORAD_ID`")
    assert cli_problems(wrong) == ["sentinel screen --primry 41599", "sentinel screen --primary NORAD_ID"]
    right = parse_markdown("```\nSENTINEL_DB=:memory: ./venv/bin/sentinel serve --port 18799\n```\n")
    assert cli_problems(right) == []


def test_a_proof_point_number_its_report_does_not_state_is_caught():
    wrong = "| W2 | Most urgent record in 38.3 s. | [DDIL](ddil-results.md#limited) |"
    assert proof_point_problems(wrong) == ["W2: 38.3 is not in ddil-results.md"]
    elsewhere = "| W3 | Right tool 0.460 of the time. | [DDIL](ddil-results.md) |"
    assert proof_point_problems(elsewhere) == ["W3: 0.460 is not in ddil-results.md"]
    unlinked = "| W1 | 53 events. | `tests/test_tier3_cara_validation.py` |"
    assert proof_point_problems(unlinked) == ["W1: states 53 but links no generated report"]
    right = "| W2 | 12.1 s against 46.8 s. | [DDIL](ddil-results.md#limited) (REQ-DDIL-004) |"
    assert proof_point_problems(right) == []


def test_a_long_or_unsupported_win_theme_is_caught():
    themes = "- **W1. Short.** Backed.\n- **W2. Long.** " + "word " * 25 + "\n"
    proofs = "| W1 | A claim. | `tests/test_cdm_codec.py` |\n"
    assert win_theme_problems(themes, proofs) == [
        "W2 has 26 words (at most 25)",
        "W2 has no proof point with evidence",
    ]


# ------------------------------------------------------ the real documents


def test_every_program_document_exists():
    assert [doc.name for doc in ALL_DOCUMENTS if not doc.is_file()] == []


@pytest.mark.parametrize("doc", ALL_DOCUMENTS, ids=_name)
def test_every_make_target_and_variable_named_exists(doc):
    assert missing_make_targets(document(doc)) == []


@pytest.mark.parametrize("doc", ALL_DOCUMENTS, ids=_name)
def test_every_script_path_link_and_test_named_exists(doc):
    assert missing_references(document(doc), doc.parent) == []


@pytest.mark.parametrize("doc", ALL_DOCUMENTS, ids=_name)
def test_every_sentinel_command_parses_with_the_real_cli(doc):
    assert cli_problems(document(doc)) == []


def test_every_proof_point_number_is_in_the_generated_report_it_links():
    proofs = section(WHITE_PAPER.read_text(encoding="utf-8"), "Proof points")
    assert proof_point_problems(proofs) == []


def test_every_win_theme_is_short_and_backed_by_a_proof_point():
    text = WHITE_PAPER.read_text(encoding="utf-8")
    themes, proofs = section(text, "Win themes"), section(text, "Proof points")
    assert themes.count("- **W") >= 3
    assert win_theme_problems(themes, proofs) == []


@pytest.mark.parametrize("name", THIRD_PARTY_PRODUCTS)
def test_no_third_party_product_is_named(name):
    named = [doc.name for doc in ALL_DOCUMENTS if name.lower() in doc.read_text(encoding="utf-8").lower()]
    assert named == []
