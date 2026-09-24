"""Checks for the program documents: the white paper, the quad chart, the
demo script and the install guide.

tests/doclint.py reads documents and holds them to their paths, make
targets, CLI subcommands and registered claims (tests/test_docs.py applies
it to every Markdown page). This module reuses it and adds only what it does
not cover:

- the quad chart's visible text, which is SVG rather than Markdown;
- make variables, scripts run beside the bundle, and test functions;
- whole `sentinel` command lines, parsed by the real CLI parser;
- coverage: every proof-point number is a registered claim on a generated report;
- the white paper's win themes.
"""

from __future__ import annotations

import pathlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable

from sentinel.ai.grounding import numbers_in_text
from sentinel.cli import build_parser
from tests.doclint import (
    Claim,
    Markdown,
    cli_tree,
    commands,
    load_claims,
    makefile_targets,
    missing_paths,
    parse_markdown,
    unknown_cli_commands,
    unknown_make_targets,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
MAKEFILE = ROOT / "Makefile"
PROGRAM_DOCS = tuple(DOCS / n for n in ("white-paper.md", "quad-chart.md", "demo-script.md", "install-guide.md"))
QUAD_CHART_SVG = DOCS / "quad-chart.svg"
CLAIMS = load_claims(ROOT / "tests" / "doc_claims.toml")

# The only sources of numbers. Each is written by a script and never edited:
# scripts/validation_report.py, python -m harness.report, scripts/ai_eval.py
# and scripts/trace.py.
GENERATED_REPORTS = tuple(
    f"docs/{n}" for n in ("validation-report.md", "ddil-results.md", "ai-eval.md", "traceability.md")
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


def generated_text() -> str:
    return "\n".join((ROOT / report).read_text(encoding="utf-8") for report in GENERATED_REPORTS)


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


# ------------------------------------------------- doclint, for the SVG too


def drift_problems(md: Markdown, doc_dir: pathlib.Path) -> list[str]:
    """tests/test_docs.py's rules (paths, make targets, CLI subcommands), for a non-Markdown document."""
    makefile = MAKEFILE.read_text(encoding="utf-8")
    argvs = commands(md)
    return (
        missing_paths(md, doc_dir, ROOT)
        + [f"make {t}" for t in unknown_make_targets(argvs, makefile_targets(makefile))]
        + [f"sentinel {c}" for c in unknown_cli_commands(argvs, cli_tree(build_parser()))]
    )


# ----------------------------------------------------------------- commands


def unknown_make_variables(md: Markdown) -> list[str]:
    """NAME=value arguments to make that the Makefile never reads."""
    read = set(re.findall(r"\$\((\w+)\)", MAKEFILE.read_text(encoding="utf-8")))
    named = (w.split("=", 1)[0] for argv in commands(md) if argv[0] == "make" for w in argv[1:] if "=" in w)
    return [name for name in dict.fromkeys(named) if name not in read]


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


def missing_references(md: Markdown) -> list[str]:
    """Scripts named without a directory (run beside the bundle), and test functions, that do not exist."""
    return _missing_site_scripts(md) + _missing_tests(md)


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


def table_rows(text: str) -> list[list[str]]:
    rows = [line.strip() for line in text.splitlines() if line.lstrip().startswith("|")]
    return [[c.strip() for c in row.strip("|").split("|")] for row in rows if not re.match(r"\|\s*:?-", row)]


def unregistered_proof_point_numbers(proofs: str, claims: Iterable[Claim]) -> list[str]:
    """Numbers a proof point states that no registered claim on a generated report quotes.

    A row is | theme | claim ... | evidence |; the evidence column names files,
    tests and requirement ids, so only the claim columns count. A claim covers
    a row when its quoted text is part of the row's claim text. test_docs.py
    then holds each claim's numbers to its report.
    """
    on_reports = [c for c in claims if c.source in GENERATED_REPORTS]
    problems = []
    for row in table_rows(proofs):
        theme, text = row[0], _squash(" ".join(row[1:-1]))
        if not _THEME_ID.fullmatch(theme):
            continue
        covering = [c for c in on_reports if _squash(c.quoted) in text]
        registered = {n for c in covering for n in numbers_in_text(c.quoted)}
        problems += [f"{theme}: {n}" for n in dict.fromkeys(numbers_in_text(text)) if n not in registered]
    return problems


def _squash(text: str) -> str:
    return " ".join(text.split())


# ------------------------------------------------------------------ themes


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
