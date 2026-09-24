"""The program documents name only commands that exist and state only
numbers the repository generated.

The documents are the white paper, the quad chart, the demo script and the
install guide. tests/test_docs.py already holds every Markdown page under
docs/ to its paths, links, make targets and CLI subcommands, and holds each
number registered in tests/doc_claims.toml to its source. These tests add
only what that does not cover:

- the white paper's proof-point numbers are all registered there, against a
  generated report, so none can go unchecked;
- the quad chart, which is SVG, gets the same drift guards as Markdown;
- make variables, scripts run beside the bundle, test functions, and whole
  `sentinel` command lines (arguments, not only the subcommand);
- the win themes, and no third-party product names.

Each check is first shown to catch a deliberately wrong input, then run
against the real documents.
"""

import pytest

from tests.doclint import Claim, Markdown, parse_markdown

from .doccheck import (
    CLAIMS,
    DOCS,
    PROGRAM_DOCS,
    QUAD_CHART_SVG,
    cli_problems,
    document,
    drift_problems,
    missing_references,
    section,
    unknown_make_variables,
    unregistered_proof_point_numbers,
    win_theme_problems,
)

WHITE_PAPER = DOCS / "white-paper.md"
ALL_DOCUMENTS = (*PROGRAM_DOCS, QUAD_CHART_SVG)

# Products that belong in public documents only as integration targets, and
# are better left out of these ones entirely.
THIRD_PARTY_PRODUCTS = ("Privateer", "Wayfinder", "Crow's Nest")


def _name(path) -> str:
    return path.name


def _texts(texts: list[str]) -> Markdown:
    """Text read the way a non-Markdown document's visible text is read."""
    return Markdown(code=tuple(texts), links=())


def _claim(quoted: str, source: str = "docs/ddil-results.md") -> Claim:
    return Claim("c", "docs/white-paper.md", quoted, source, ("unused here",))


# --------------------------------------------------------- the checks catch it


def test_a_proof_point_number_no_claim_registers_is_caught():
    proofs = (
        "| Theme | Proof point | Evidence |\n"
        "|---|---|---|\n"
        "| W2 | Most urgent record in 12.1 s, against 46.8 s. | [DDIL](ddil-results.md) |\n"
        "| W3 | Right tool for 0.460 of requests. | [eval](ai-eval.md) |\n"
        "| W1 | Summaries of at most 256 bytes. | `tests/sync/test_hub_edge.py` |\n"
        "| W5 | No numbers here. | `tests/test_cdm_codec.py` (REQ-MOSA-001) |\n"
    )
    claims = [
        _claim("Most urgent record in 12.1 s"),                        # 46.8 left out
        _claim("Summaries of at most 256 bytes.", "tests/sync/test_hub_edge.py"),  # not a report
    ]
    assert unregistered_proof_point_numbers(proofs, claims) == [
        "W2: 46.8",
        "W3: 0.460",
        "W1: 256",
    ]
    claims.append(_claim("against 46.8 s."))
    assert unregistered_proof_point_numbers(proofs.splitlines()[2], claims) == []


def test_an_svg_gets_the_same_drift_guards_as_markdown():
    md = _texts(["make no-such-target", "sentinel launch", "see docs/gone.md", "make report"])
    assert drift_problems(md, DOCS) == ["docs/gone.md", "make no-such-target", "sentinel launch"]


def test_an_unknown_make_variable_is_named():
    md = parse_markdown("```\nmake screen PRIMAY=41599 && make airgap-selftest\n```\n`make screen PRIMARY=1 HOURS=2`")
    assert unknown_make_variables(md) == ["PRIMAY"]


def test_a_missing_site_script_or_test_function_is_named():
    md = parse_markdown(
        "```\nCOSIGN=./cosign unshare -rn ./no_such.sh bundle.tar.gz\n```\n"
        "`tests/test_cdm_codec.py::test_that_does_not_exist` `./verify_signature.sh x` "
        "`tests/test_cdm_codec.py::test_every_nasa_cdm_parses_and_round_trips`"
    )
    assert missing_references(md) == [
        "deploy/bundle/no_such.sh",
        "tests/test_cdm_codec.py::test_that_does_not_exist",
    ]


def test_a_command_the_real_cli_rejects_is_named():
    wrong = parse_markdown("`uv run sentinel screen --primry 41599`\n\n`sentinel screen --primary NORAD_ID`")
    assert cli_problems(wrong) == ["sentinel screen --primry 41599", "sentinel screen --primary NORAD_ID"]
    right = parse_markdown("```\nSENTINEL_DB=:memory: ./venv/bin/sentinel serve --port 18799\n```\n`sentinel`")
    assert cli_problems(right) == []


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


def test_every_proof_point_number_is_registered_against_a_generated_report():
    proofs = section(WHITE_PAPER.read_text(encoding="utf-8"), "Proof points")
    assert unregistered_proof_point_numbers(proofs, CLAIMS) == []


def test_the_quad_chart_passes_the_doc_drift_guards():
    assert drift_problems(document(QUAD_CHART_SVG), DOCS) == []


@pytest.mark.parametrize("doc", ALL_DOCUMENTS, ids=_name)
def test_every_make_variable_named_is_one_the_makefile_reads(doc):
    assert unknown_make_variables(document(doc)) == []


@pytest.mark.parametrize("doc", ALL_DOCUMENTS, ids=_name)
def test_every_site_script_and_test_function_named_exists(doc):
    assert missing_references(document(doc)) == []


@pytest.mark.parametrize("doc", ALL_DOCUMENTS, ids=_name)
def test_every_sentinel_command_parses_with_the_real_cli(doc):
    assert cli_problems(document(doc)) == []


def test_every_win_theme_is_short_and_backed_by_a_proof_point():
    text = WHITE_PAPER.read_text(encoding="utf-8")
    themes, proofs = section(text, "Win themes"), section(text, "Proof points")
    assert themes.count("- **W") >= 3
    assert win_theme_problems(themes, proofs) == []


@pytest.mark.parametrize("name", THIRD_PARTY_PRODUCTS)
def test_no_third_party_product_is_named(name):
    named = [doc.name for doc in ALL_DOCUMENTS if name.lower() in doc.read_text(encoding="utf-8").lower()]
    assert named == []
