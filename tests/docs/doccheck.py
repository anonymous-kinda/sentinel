"""Checks for the program documents: the white paper, the quad chart, the
demo script and the install guide.

Two rules. Every command, script, file and test a document names exists.
Every number it states comes from a report the repository generates.
Shared by tests/docs/test_program_docs.py and tests/docs/test_quad_chart.py.
"""

from __future__ import annotations

import pathlib
import re
import shlex
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator

from sentinel.cli import build_parser

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

# Where a named path must exist. Build output (dist/, web/dist, .tools/) is
# not source and is not checked. A bare script name is one of the scripts
# that cross the air gap beside the bundle.
SOURCE_ROOTS = {
    "docs", "tests", "deploy", "scripts", "sentinel", "harness", "mbse", "evals",
    "fixtures", "compliance", "supplychain", "web", ".github",
}
TOP_LEVEL_FILES = {"Makefile", "pyproject.toml", ".importlinter"}
FILE_SUFFIXES = (
    ".sh", ".py", ".md", ".yml", ".yaml", ".toml", ".json", ".jsonl", ".lock",
    ".tmpl", ".sysml", ".svg", ".service", ".j2", ".tsx", ".ts",
)
SITE_SCRIPTS = ROOT / "deploy" / "bundle"

# ------------------------------------------------------------------ numbers

_NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?"
# A quantity as a document states it: 53, 64,058, 2.7, 1.5e-08, 6.9x, $17.50.
# Digits glued on the left to a letter, dot, hyphen, slash, colon, section
# sign or hash, or followed by a hyphen and more, are identifiers instead:
# ADR-007, x86_64, SysML v2, CCSDS 508.0-B-1, 2026-09-24, §4401, #5-heading.
_STATED = re.compile(rf"(?<![\w.\-/:§#]){_NUMBER}(?![.,]?\d)(?!-\w)")
_ANY_NUMBER = re.compile(_NUMBER)


def value(number: str) -> float:
    return float(number.replace(",", ""))


def stated_numbers(text: str) -> list[str]:
    return _STATED.findall(text)


def report_values(reports: Iterable[pathlib.Path] = GENERATED_REPORTS) -> set[float]:
    """Every number a report contains, however it is written there."""
    return {value(n) for report in reports for n in _ANY_NUMBER.findall(report.read_text())}


# ------------------------------------------------------------ document text

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.M | re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
_HEADING = re.compile(r"(#+)\s+(.*)")


def code_snippets(markdown: str) -> list[str]:
    """Fenced blocks and inline code: where a document names commands and paths."""
    return _FENCE.findall(markdown) + _INLINE_CODE.findall(_FENCE.sub("", markdown))


def section(markdown: str, title: str) -> str:
    """The body under the first heading containing title, to the next heading at its level."""
    lines, in_fence = markdown.splitlines(), False
    for i, line in enumerate(lines):
        in_fence ^= line.startswith("```")
        heading = None if in_fence else _HEADING.match(line)
        if heading and title.lower() in heading.group(2).lower():
            return "\n".join(_until_heading(lines[i + 1 :], len(heading.group(1))))
    raise LookupError(f"no section titled {title!r}")


def _until_heading(lines: list[str], level: int) -> Iterator[str]:
    in_fence = False
    for line in lines:
        in_fence ^= line.startswith("```")
        heading = None if in_fence else _HEADING.match(line)
        if heading and len(heading.group(1)) <= level:
            return
        yield line


def svg_texts(path: pathlib.Path) -> list[str]:
    """The text a reader sees on the chart (and its title and description)."""
    root = ET.parse(path).getroot()
    return [
        "".join(el.itertext()).strip()
        for el in root.iter()
        if el.tag.rsplit("}", 1)[-1] in {"text", "title", "desc"}
    ]


def svg_text(path: pathlib.Path) -> str:
    return "\n".join(svg_texts(path))


def broken_links(markdown: str, base: pathlib.Path) -> list[str]:
    targets = (t for t in _LINK.findall(markdown) if not re.match(r"[a-z]+:|#", t))
    return [t for t in targets if not (base / t.split("#")[0]).exists()]


def linked_files(text: str, base: pathlib.Path = DOCS) -> set[pathlib.Path]:
    return {(base / t.split("#")[0]).resolve() for t in _LINK.findall(text) if not re.match(r"[a-z]+:|#", t)}


# ----------------------------------------------------------------- commands

_SHELL_OPERATORS = {"&&", "||", ";", "|", "&", ">", ">>", "<", "2>&1"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
_MAKE_CALL = re.compile(r"(?<![\w-])make((?:[ \t]+(?:[A-Za-z_]\w*=\S*|[a-z][\w-]*))+)")


def command_lines(snippet: str) -> list[list[str]]:
    """Each simple command in a snippet, as tokens, split at shell operators."""
    commands: list[list[str]] = []
    for line in snippet.replace("\\\n", " ").splitlines():
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            tokens = line.split()
        current: list[str] = []
        for token in tokens:
            if token in _SHELL_OPERATORS:
                commands.append(current)
                current = []
            else:
                current.append(token)
        commands.append(current)
    return [c for c in commands if c]


def _program(tokens: list[str]) -> list[str]:
    """The command itself: environment assignments, `uv run` and `sudo` dropped."""
    rest = list(tokens)
    while rest and _ASSIGNMENT.match(rest[0]):
        rest.pop(0)
    for wrapper in (["uv", "run"], ["sudo"]):
        if rest[: len(wrapper)] == wrapper:
            rest = rest[len(wrapper) :]
    return rest


def makefile_targets() -> set[str]:
    return set(re.findall(r"^([\w.-]+):(?!=)", MAKEFILE.read_text(), re.M)) - {".PHONY"}


def makefile_variables() -> set[str]:
    return set(re.findall(r"\$\((\w+)\)", MAKEFILE.read_text()))


def missing_make_targets(snippets: Iterable[str]) -> list[str]:
    targets, variables = makefile_targets(), makefile_variables()
    missing = []
    for snippet in snippets:
        for call in _MAKE_CALL.findall(snippet):
            for arg in call.split():
                name, is_variable = arg.split("=", 1)[0], "=" in arg
                known = variables if is_variable else targets
                if name not in known:
                    missing.append(f"{'variable' if is_variable else 'target'} {name}")
    return missing


def cli_problems(snippets: Iterable[str]) -> list[str]:
    """Every `sentinel ...` command that the real argument parser rejects."""
    problems = []
    for snippet in snippets:
        for tokens in command_lines(snippet):
            program = _program(tokens)
            if program and (program[0] == "sentinel" or program[0].endswith("/sentinel")):
                if not _parses(program[1:]):
                    problems.append(" ".join(["sentinel", *program[1:]]))
    return problems


def _parses(argv: list[str]) -> bool:
    try:
        build_parser().parse_args(argv)
    except SystemExit as exit_:
        return not exit_.code
    return True


# ------------------------------------------------------------------- paths

_TOKEN = re.compile(r"[^\s`'\"()\[\],;=|&<>]+")
_MODULE = re.compile(r"-m\s+([\w.]+)")


def missing_references(snippets: Iterable[str]) -> list[str]:
    """Named scripts, files, tests and modules that do not exist."""
    missing = []
    for snippet in snippets:
        for token in _TOKEN.findall(snippet):
            reference = _reference(token.rstrip(".:"))
            if reference and not _exists(*reference):
                missing.append(_describe(*reference))
        for module in _MODULE.findall(snippet):
            path = pathlib.Path(*module.split("."))
            if path.parts[0] in SOURCE_ROOTS and not _module_exists(path):
                missing.append(f"{path}.py")
    return missing


def _reference(token: str) -> tuple[pathlib.Path, str] | None:
    """(file, test name or "") for a token that names a repository file."""
    if "$" in token or "://" in token or token.startswith("/"):
        return None
    path, _, name = token.partition("::")
    path = path.removeprefix("./")
    if "/" not in path:
        if path in TOP_LEVEL_FILES:
            return ROOT / path, name
        return (SITE_SCRIPTS / path, name) if path.endswith(".sh") else None
    if path.split("/")[0] in SOURCE_ROOTS and path.endswith(FILE_SUFFIXES):
        return ROOT / path, name
    return None


def _exists(path: pathlib.Path, name: str) -> bool:
    if not path.is_file():
        return False
    return not name or re.search(rf"^\s*(?:def|class)\s+{re.escape(name)}\b", path.read_text(), re.M) is not None


def _describe(path: pathlib.Path, name: str) -> str:
    relative = path.relative_to(ROOT).as_posix()
    return f"{relative}::{name}" if name else relative


def _module_exists(path: pathlib.Path) -> bool:
    return (ROOT / path).with_suffix(".py").is_file() or (ROOT / path / "__init__.py").is_file()


# ------------------------------------------------------ white paper structure

_THEME = re.compile(r"^- \*\*(W\d+)\.\s*(.+)$", re.M)
_THEME_ID = re.compile(r"\bW\d+\b")


def table_rows(text: str) -> list[list[str]]:
    rows = [line.strip() for line in text.splitlines() if line.lstrip().startswith("|")]
    return [[c.strip() for c in row.strip("|").split("|")] for row in rows if not re.match(r"\|\s*:?-", row)]


def proof_point_problems(proofs: str) -> list[str]:
    """Each number in a proof point must be in a generated report the same row links."""
    reports = set(GENERATED_REPORTS)
    problems = []
    for row in table_rows(proofs):
        theme = row[0]
        numbers = [n for cell in row[1:] for n in stated_numbers(_without_links(cell))]
        cited = linked_files(" ".join(row)) & {r.resolve() for r in reports}
        if numbers and not cited:
            problems.append(f"{theme}: states {', '.join(numbers)} but links no generated report")
            continue
        known = report_values(cited)
        names = ", ".join(sorted(p.name for p in cited))
        problems += [f"{theme}: {n} is not in {names}" for n in numbers if value(n) not in known]
    return problems


def _without_links(cell: str) -> str:
    """A cell's text with link targets and code removed: those are evidence, not claims."""
    return _INLINE_CODE.sub("", re.sub(r"\]\([^)]*\)", "]", cell))


def win_theme_problems(themes: str, proofs: str) -> list[str]:
    backed = {
        theme
        for row in table_rows(proofs)
        if _LINK.search(row[-1]) or _INLINE_CODE.search(row[-1])
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
