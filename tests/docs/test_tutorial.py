"""The tutorial keeps its promises: every chapter the overview lists exists,
and every written chapter has the sections the overview says it has.

A reader who learns where "Check yourself" is in one chapter finds it in
every chapter. A chapter still marked as being written is held to the list
only once it is written.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
TUTORIAL = ROOT / "docs" / "tutorial"
OVERVIEW = TUTORIAL / "README.md"
SECTIONS = (
    "What you will learn",
    "Why it exists",
    "Concepts",
    "Code walkthrough",
    "Try it",
    "Design choices",
    "How it fails",
    "Check yourself",
    "Where next",
)
BEING_WRITTEN = "This chapter is being written."


def listed_chapters(overview: str) -> list[str]:
    return re.findall(r"^\| \d+ \| \[[^\]]+\]\(([^)]+\.md)\) \|", overview, re.MULTILINE)


def section_problems(text: str) -> list[str]:
    """The sections missing, then any out of order."""
    headings = re.findall(r"^## (.+?)\s*$", text, re.MULTILINE)
    missing = [s for s in SECTIONS if s not in headings]
    if missing:
        return [f"missing: {s}" for s in missing]
    order = [headings.index(s) for s in SECTIONS]
    return [] if order == sorted(order) else ["sections out of order"]


CHAPTERS = listed_chapters(OVERVIEW.read_text())


def test_the_overview_lists_every_chapter_file_and_nothing_else():
    on_disk = sorted(p.name for p in TUTORIAL.glob("*.md") if p.name != "README.md")
    assert sorted(CHAPTERS) == on_disk


def test_the_overview_names_the_sections_this_test_checks():
    overview = OVERVIEW.read_text()
    assert all(f"**{s}**" in overview for s in SECTIONS)


def test_every_written_chapter_has_every_section_in_order():
    written = {c: (TUTORIAL / c).read_text() for c in CHAPTERS}
    problems = {c: section_problems(t) for c, t in written.items() if BEING_WRITTEN not in t}
    assert {c: p for c, p in problems.items() if p} == {}


def test_the_section_check_catches_a_missing_and_a_misordered_section():
    good = "\n".join(f"## {s}\n\nText." for s in SECTIONS)
    assert section_problems(good) == []
    assert section_problems(good.replace("## Try it", "## Try this")) == ["missing: Try it"]
    swapped = good.replace("## Concepts", "## TMP").replace("## Why it exists", "## Concepts").replace("## TMP", "## Why it exists")
    assert section_problems(swapped) == ["sections out of order"]
