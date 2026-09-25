"""The documents lead with value, written for the reader each one serves.

CLAUDE.md's "Docs are value-first" rule, in the parts a test can hold:

- every ADR opens with what it buys and what it costs, right under its title;
- the README's limits are a top-level section placed straight after its value
  section, and they name the exercise-only data, that nothing is fielded, that
  no ATO is claimed, and the open gaps in SECURITY.md;
- the documentation index says which documents are for which reader.

Numbers are not checked here: tests/doc_claims.toml holds each quoted number to
its generated source. Each check is first shown to catch a deliberately wrong
input, then run against the real documents.
"""

import re

from .doccheck import DOCS, ROOT

SYSTEM_DESIGN = DOCS / "system-design.md"
README = ROOT / "README.md"
INDEX = DOCS / "index.md"

_ADR = re.compile(r"^### (ADR-\d{3})\b")
_FENCE = re.compile(r"^\s*(```|~~~)")
BUYS, COSTS = "**Buys.** ", "**Costs.** "

# What the README's limits must state, as the words a reader would look for.
LIMITS = {
    "exercise data": "exercise",
    "nothing fielded": "fielded",
    "no ATO claimed": "ATO",
    "the open gaps": "SECURITY.md",
}

# The reader split CLAUDE.md sets: who reads what first.
READERS = {
    "operator or program office": ("README.md", "docs/white-paper.md", "docs/quad-chart.md"),
    "engineer": ("docs/technical-guide.md", "docs/system-design.md", "docs/icd/", "CONTRIBUTING.md"),
}


def _prose_lines(markdown: str) -> list[str]:
    """Lines outside fenced code, so a `#` inside a code block is not a heading."""
    lines, fenced = [], False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            lines.append(line)
    return lines


# ------------------------------------------------------------------ the ADRs


def adr_openings(markdown: str) -> dict[str, list[str]]:
    """ADR id -> its first two non-blank lines under the title."""
    openings: dict[str, list[str]] = {}
    current = None
    for line in _prose_lines(markdown):
        heading = _ADR.match(line)
        if heading:
            current = heading.group(1)
            openings[current] = []
        elif line.startswith("#"):
            current = None
        elif current and line.strip() and len(openings[current]) < 2:
            openings[current].append(line.strip())
    return openings


def adr_problems(markdown: str) -> list[str]:
    problems = []
    for adr, lines in adr_openings(markdown).items():
        first, second = [*lines, "", ""][:2]
        if not (first.startswith(BUYS) and first.removeprefix(BUYS).strip()):
            problems.append(f"{adr} does not open with a Buys line")
        if not (second.startswith(COSTS) and second.removeprefix(COSTS).strip()):
            problems.append(f"{adr} has no Costs line after its Buys line")
    return problems


# ------------------------------------------------------------ README limits


def top_sections(markdown: str) -> list[tuple[str, str]]:
    """(title, body) for each `## ` section, in order."""
    sections: list[tuple[str, list[str]]] = []
    for line in _prose_lines(markdown):
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections:
            sections[-1][1].append(line)
    return [(title, "\n".join(body)) for title, body in sections]


def limits_problems(markdown: str) -> list[str]:
    titles = [title for title, _ in top_sections(markdown)]
    if "Limits" not in titles:
        return ["no '## Limits' section"]
    problems = []
    if titles.index("Limits") != 1:
        problems.append("Limits is not the section straight after the value section")
    body = dict(top_sections(markdown))["Limits"].lower()
    problems += [f"Limits does not state {what}" for what, word in LIMITS.items() if word.lower() not in body]
    return problems


# -------------------------------------------------------------------- index


def reader_problems(index: str) -> list[str]:
    """Each reader's row in the index names the documents written for that reader."""
    rows = {}
    for line in index.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and len(cells) > 1:
            rows[cells[0].strip("*").lower()] = " ".join(cells[1:])
    problems = []
    for reader, documents in READERS.items():
        row = rows.get(reader)
        if row is None:
            problems.append(f"no row for the {reader}")
            continue
        problems += [f"{reader}: {doc}" for doc in documents if f"`{doc}`" not in row]
    return problems


# --------------------------------------------------------- the checks catch it


def test_an_adr_without_buys_and_costs_first_is_caught():
    markdown = (
        "### ADR-001 — Right\n\n**Buys.** Urgent data first.\n**Costs.** A protocol of our own.\n\n"
        "**Status:** Accepted\n\n"
        "### ADR-002 — Status first\n\n**Status:** Accepted\n\n**Buys.** x\n\n**Costs.** y\n\n"
        "### ADR-003 — No costs\n\n**Buys.** Something.\n\n**Decision.** z\n\n"
        "### ADR-004 — Empty lines\n\n**Buys.**\n**Costs.** \n\n"
        "## 4. Core Pipeline\n\n**Buys.** not an ADR\n"
    )
    assert adr_problems(markdown) == [
        "ADR-002 does not open with a Buys line",
        "ADR-002 has no Costs line after its Buys line",
        "ADR-003 has no Costs line after its Buys line",
        "ADR-004 does not open with a Buys line",
        "ADR-004 has no Costs line after its Buys line",
    ]


def test_a_readme_whose_limits_are_missing_buried_or_incomplete_is_caught():
    value = "## What it gives an operator\n\nValue.\n\n"
    limits = "## Limits\n\nExercise and public data only. Nothing is fielded. No ATO is claimed. See `SECURITY.md`.\n\n"
    buried = value + "## Running it\n\n```\n## Limits (in a code block)\n```\n\n" + limits
    assert limits_problems(value + limits) == []
    assert limits_problems(value) == ["no '## Limits' section"]
    assert limits_problems(buried) == ["Limits is not the section straight after the value section"]
    assert limits_problems(value + "## Limits\n\nNothing is fielded.\n") == [
        "Limits does not state exercise data",
        "Limits does not state no ATO claimed",
        "Limits does not state the open gaps",
    ]


def test_an_index_that_does_not_say_who_reads_what_is_caught():
    right = (
        "| Reader | Start with |\n|---|---|\n"
        "| **Operator or program office** | `README.md`, `docs/white-paper.md`, `docs/quad-chart.md` |\n"
        "| **Engineer** | `docs/technical-guide.md`, `docs/system-design.md`, `docs/icd/`, `CONTRIBUTING.md` |\n"
    )
    assert reader_problems(right) == []
    assert reader_problems(right.replace(", `docs/quad-chart.md`", "")) == [
        "operator or program office: docs/quad-chart.md"
    ]
    assert reader_problems(right.splitlines()[2]) == ["no row for the engineer"]


# ------------------------------------------------------ the real documents


def test_every_adr_opens_with_what_it_buys_and_what_it_costs():
    text = SYSTEM_DESIGN.read_text(encoding="utf-8")
    assert len(adr_openings(text)) >= 12
    assert adr_problems(text) == []


def test_the_readme_states_its_limits_straight_after_its_value():
    assert limits_problems(README.read_text(encoding="utf-8")) == []


def test_the_index_says_which_documents_are_for_which_reader():
    assert reader_problems(INDEX.read_text(encoding="utf-8")) == []
