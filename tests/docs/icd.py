"""What the ICD drift tests share: reading a document's tables, and reading
facts out of the source by AST, so neither side is restated by hand."""

from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
ICD = ROOT / "docs" / "icd"

_HEADING = re.compile(r"^(#+)\s+(.*?)\s*$")
_BACKTICKED = re.compile(r"`([^`]+)`")


# ------------------------------------------------------------------ documents
def section(markdown: str, heading: str) -> str:
    """The text under `heading`, up to the next heading of the same or a higher level."""
    lines = markdown.splitlines()
    for start, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match[2] == heading:
            level = len(match[1])
            body = []
            for following in lines[start + 1 :]:
                nested = _HEADING.match(following)
                if nested and len(nested[1]) <= level:
                    break
                body.append(following)
            return "\n".join(body)
    raise AssertionError(f"no heading {heading!r}")


def table_rows(markdown: str, heading: str) -> list[list[str]]:
    """Body rows of the first table under `heading`, as stripped cells."""
    rows = []
    for line in section(markdown, heading).splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows[1:]  # drop the header row


def backticked(text: str) -> list[str]:
    return _BACKTICKED.findall(text)


def column(markdown: str, heading: str, index: int = 0) -> set[str]:
    """Every backticked token in one column of the table under `heading`."""
    return {token for row in table_rows(markdown, heading) for token in backticked(row[index])}


def compare(documented: set, actual: set, what: str) -> list[str]:
    """Both directions: in the code but undocumented, and documented but gone."""
    problems = [f"{what} {item} is not documented" for item in sorted(actual - documented, key=str)]
    problems += [f"{what} {item} is documented but not in the code" for item in sorted(documented - actual, key=str)]
    return problems


def drop_row(markdown: str, token: str) -> str:
    """The document with the table row naming `token` removed: a stale copy."""
    kept = [line for line in markdown.splitlines() if not (line.startswith("|") and f"`{token}`" in line)]
    assert len(kept) < len(markdown.splitlines()), f"no row names {token}"
    return "\n".join(kept) + "\n"


# --------------------------------------------------------------------- source
def tree(relative: str) -> ast.Module:
    path = ROOT / relative
    return ast.parse(path.read_text(), filename=str(path))


def trees(*patterns: str) -> list[ast.Module]:
    return [tree(str(p.relative_to(ROOT))) for pattern in patterns for p in sorted(ROOT.glob(pattern))]


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def call_arguments(modules: list[ast.Module], callee: str, position: int) -> set[str]:
    """String constants passed at `position` to every call of `callee`."""
    found = set()
    for module in modules:
        for node in ast.walk(module):
            if isinstance(node, ast.Call) and _callee(node) == callee and len(node.args) > position:
                arg = node.args[position]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return found


def string_constants(modules: list[ast.Module], pattern: str) -> set[str]:
    """Every string constant that is, in full, a match for `pattern`."""
    regex = re.compile(pattern)
    return {
        node.value
        for module in modules
        for node in ast.walk(module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and regex.fullmatch(node.value)
    }


def function(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"no function {name}")
