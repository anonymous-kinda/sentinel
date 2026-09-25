"""The documents lead with value, written for the reader each one serves.

CLAUDE.md's "Docs are value-first" rule, in the parts a test can hold:

- the README's limits are a top-level section placed straight after its value
  section, and they name the exercise-only data, that nothing is fielded, that
  no ATO is claimed, and the open gaps in SECURITY.md.

Numbers are not checked here: tests/doc_claims.toml holds each quoted number to
its generated source. Each check is first shown to catch a deliberately wrong
input, then run against the real documents.
"""

import re

from .doccheck import ROOT

README = ROOT / "README.md"

_FENCE = re.compile(r"^\s*(```|~~~)")

# What the README's limits must state, as the words a reader would look for.
LIMITS = {
    "exercise data": "exercise",
    "nothing fielded": "fielded",
    "no ATO claimed": "ATO",
    "the open gaps": "SECURITY.md",
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


# --------------------------------------------------------- the checks catch it


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


# ------------------------------------------------------ the real documents


def test_the_readme_states_its_limits_straight_after_its_value():
    assert limits_problems(README.read_text(encoding="utf-8")) == []
