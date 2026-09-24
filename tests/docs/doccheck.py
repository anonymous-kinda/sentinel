"""Checks for the program documents: the white paper, the quad chart, the
demo script and the install guide.

Built on tests/doclint.py, which reads a document and checks its paths,
links and make targets, and on the assistant's number-grounding rule
(sentinel.ai.grounding, ADR-007). This module adds only what those do not
cover:

- the quad chart's text, which is SVG rather than Markdown;
- make variables, scripts run beside the bundle, and test functions;
- full `sentinel` command lines, parsed by the real CLI parser;
- proof-point numbers, each grounded in the generated report its row links;
- the white paper's win themes.
"""

from __future__ import annotations

import pathlib
import re
import xml.etree.ElementTree as ET

from sentinel.ai.grounding import check_grounding, numbers_in_text
from sentinel.cli import build_parser
from tests.doclint import Markdown, commands, makefile_targets, missing_paths, parse_markdown, unknown_make_targets

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
MAKEFILE = ROOT / "Makefile"
PROGRAM_DOCS = tuple(DOCS / n for n in ("white-paper.md", "quad-chart.md", "demo-script.md", "install-guide.md"))
QUAD_CHART_SVG = DOCS / "quad-chart.svg"

# The only sources of numbers. Each is written by a script and never edited:
# scripts/validation_report.py, python -m harness.report, scripts/ai_eval.py
# and scripts/trace.py.
GENERATED_REPORTS = tuple(
    DOCS / n for n in ("validation-report.md", "ddil-results.md", "ai-eval.md", "traceability.md")
)
# A script named without a directory runs beside the bundle, at the site.
SITE_SCRIPTS = ROOT / "deploy" / "bundle"

_TEST_ID = re.compile(r"(tests/[\w/]+\.py)::(\w+)")
_THEME = re.compile(r"^- \*\*(W\d+)\.\s*(.+)$", re.M)
_THEME_ID = re.compile(r"\bW\d+\b")
_HEADING = re.compile(r"(#+)\s+(.*)")


# ------------------------------------------------------------------ reading


def document(path: pathlib.Path) -> Markdown:
    """A program document as doclint reads it. The chart's visible text counts as code."""
    if path.suffix == ".svg":
        return Markdown(code=tuple(svg_texts(path)), links=())
    return parse_markdown(path.read_text(encoding="utf-8"))


def svg_texts(path: pathlib.Path) -> list[str]:
    """The text a reader sees on the chart, with its title and description."""
    root = ET.parse(path).getroot()
    return [
        "".join(el.itertext()).strip()
        for el in root.iter()
        if el.tag.rsplit("}", 1)[-1] in {"text", "title", "desc"}
    ]


def generated_text(reports: tuple[pathlib.Path, ...] = GENERATED_REPORTS) -> str:
    return "\n".join(report.read_text(encoding="utf-8") for report in reports)


def section(markdown: str, title: str) -> str:
    """The body under the first heading containing title, up to the next heading at its level."""
    lines, in_fence = markdown.splitlines(), False
    for i, line in enumerate(lines):
        in_fence ^= line.startswith("```")
        heading = None if in_fence else _HEADING.match(line)
        if heading and title.lower() in heading.group(2).lower():
            level, body = len(heading.group(1)), []
            for following in lines[i + 1 :]:
                below = _HEADING.match(following)
                if below and len(below.group(1)) <= level:
                    break
                body.append(following)
            return "\n".join(body)
    raise LookupError(f"no section titled {title!r}")


# ----------------------------------------------------------------- commands


def missing_make_targets(md: Markdown) -> list[str]:
    """Targets the Makefile does not define, then variables it never reads (as NAME=)."""
    makefile = MAKEFILE.read_text(encoding="utf-8")
    argvs = commands(md)
    variables = set(re.findall(r"\$\((\w+)\)", makefile))
    named = [w.split("=", 1)[0] for argv in argvs if argv[0] == "make" for w in argv[1:] if "=" in w]
    missing_variables = [f"{v}=" for v in dict.fromkeys(named) if v not in variables]
    return unknown_make_targets(argvs, makefile_targets(makefile)) + missing_variables


def cli_problems(md: Markdown) -> list[str]:
    """Each `sentinel ...` command line that the real argument parser rejects.

    A bare `sentinel` names the program (or its service user), not a command.
    """
    return [
        " ".join(["sentinel", *argv[1:]])
        for argv in commands(md)
        if (argv[0] == "sentinel" or argv[0].endswith("/sentinel")) and argv[1:] and not _parses(argv[1:])
    ]


def _parses(argv: list[str]) -> bool:
    try:
        build_parser().parse_args(argv)
    except SystemExit as exit_:
        return not exit_.code
    return True


# ------------------------------------------------------------------- paths


def missing_references(md: Markdown, doc_dir: pathlib.Path) -> list[str]:
    """Paths and links (doclint), then site scripts and test functions, that do not exist."""
    return missing_paths(md, doc_dir, ROOT) + _missing_site_scripts(md) + _missing_tests(md)


def _missing_site_scripts(md: Markdown) -> list[str]:
    words = (w.strip("\"'()`").removeprefix("./") for chunk in md.code for w in chunk.split())
    scripts = dict.fromkeys(w for w in words if w.endswith(".sh") and "/" not in w)
    return [f"deploy/bundle/{s}" for s in scripts if not (SITE_SCRIPTS / s).is_file()]


def _missing_tests(md: Markdown) -> list[str]:
    ids = dict.fromkeys(_TEST_ID.findall("\n".join(md.code)))
    return [f"{path}::{name}" for path, name in ids if not _defines(ROOT / path, name)]


def _defines(path: pathlib.Path, name: str) -> bool:
    if not path.is_file():
        return False
    pattern = rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b"
    return re.search(pattern, path.read_text(encoding="utf-8"), re.M) is not None


# ----------------------------------------------------------------- numbers


def unsupported_numbers(text: str, evidence: str) -> list[str]:
    """Numbers in text that evidence does not state, at the precision text states them."""
    return check_grounding(text, evidence).unsupported


def table_rows(text: str) -> list[list[str]]:
    rows = [line.strip() for line in text.splitlines() if line.lstrip().startswith("|")]
    return [[c.strip() for c in row.strip("|").split("|")] for row in rows if not re.match(r"\|\s*:?-", row)]


def proof_point_problems(proofs: str) -> list[str]:
    """Each number a proof point states must be in a generated report that the same row links.

    A row is | theme | claim ... | evidence |. The evidence column names files,
    tests and requirement ids, so only the claim columns are checked.
    """
    problems = []
    for row in table_rows(proofs):
        theme, claim = row[0], " ".join(row[1:-1])
        stated = numbers_in_text(claim)
        if not stated or not _THEME_ID.search(theme):
            continue
        cited = _cited_reports(" | ".join(row))
        if not cited:
            problems.append(f"{theme}: states {', '.join(stated)} but links no generated report")
            continue
        names = ", ".join(r.name for r in cited)
        problems += [f"{theme}: {n} is not in {names}" for n in unsupported_numbers(claim, generated_text(cited))]
    return problems


def _cited_reports(text: str) -> tuple[pathlib.Path, ...]:
    linked = {(DOCS / link.split("#", 1)[0]).resolve() for link in parse_markdown(text).links}
    return tuple(r for r in GENERATED_REPORTS if r.resolve() in linked)


def win_theme_problems(themes: str, proofs: str) -> list[str]:
    """Each win theme is at most 25 words and backed by a proof point that names evidence."""
    backed = {
        theme
        for row in table_rows(proofs)
        if parse_markdown(row[-1]).links or parse_markdown(row[-1]).code
        for theme in _THEME_ID.findall(row[0])
    }
    problems = []
    for theme, text in _THEME.findall(themes):
        words = len(text.replace("**", "").split())
        if words > 25:
            problems.append(f"{theme} has {words} words (at most 25)")
        if theme not in backed:
            problems.append(f"{theme} has no proof point with evidence")
    return problems
