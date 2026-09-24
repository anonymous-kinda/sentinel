"""The rules behind tests/test_docs.py: what a Markdown document names, and whether it exists.

Detection is deliberately conservative, so a failure is always worth reading:

- A *path* is a word in inline code or a fenced block that contains "/",
  whose first segment is a top-level directory of the repository, and that
  carries no placeholder (`<ver>`, `$VAR`, `{a,b}`). It is resolved from the
  repository root. Relative Markdown links and images are resolved from the
  document's own directory.
- A *command* is `make ...` or `sentinel ...` at the start of a code span or
  a line of a fenced block (after `$`, environment assignments or `uv run`).
- A *claim* is a quoted headline number and the generated report it comes
  from. Its numbers are held to the assistant's own grounding rule
  (sentinel.ai.grounding, ADR-007): each must match, at the precision the
  prose states it, a number in the cited source text. A quoted digest must
  match verbatim.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import glob
import re
import tomllib
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import unquote

from sentinel.ai.grounding import check_grounding, numbers_in_text

# Named by the docs, never present in a clone: build outputs and scenario
# results, each gitignored. A path under one of these is not checked.
LOCAL_ONLY = (
    "build/",            # `make compliance` working directory
    "dist/",             # bundles, SBOMs and scan results from `make bundle`, `sbom`, `scan`
    "harness/results/",  # raw DDIL results; docs/ddil-results.md is their committed report
    "web/dist/",         # the console built by `make web`
)
# Hidden top-level directories are local state (.venv, .tools, ...), except this one.
TRACKED_HIDDEN = {".github"}
PLACEHOLDER = re.compile(r"[<>{}$~…]|\.\.\.")
GLOB = re.compile(r"[*?\[]")

_FENCE = re.compile(r"^\s*(```|~~~)")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.S)
_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_COMMENT = re.compile(r"(?:^|\s)#.*$")
_SEPARATOR = re.compile(r"&&|\|\||;|\|")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_MAKE_RULE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.\- ]*?)\s*:(?!=)")
_TARGET = re.compile(r"^[A-Za-z0-9][\w.-]*$")
_SUBCOMMAND = re.compile(r"^[a-z][a-z0-9-]*$")
_DIGEST = re.compile(r"\b[0-9a-f]{40,}\b")  # a sha1/sha256 is an identifier, not a number


@dataclasses.dataclass(frozen=True)
class Markdown:
    code: tuple[str, ...]   # inline code spans, and the lines of fenced blocks
    links: tuple[str, ...]  # targets of inline links and images


@dataclasses.dataclass(frozen=True)
class Claim:
    id: str
    doc: str                  # where the number is quoted
    quoted: str               # the exact prose, whitespace-insensitive
    source: str               # the generated report it comes from
    patterns: tuple[str, ...]  # text that must appear in the source


# --- reading ------------------------------------------------------------------


def doc_files(root: Path) -> list[Path]:
    """The documents under guard: top-level rules and README, the fixtures README, and everything in docs/."""
    names = ("README.md", "CLAUDE.md", "SECURITY.md", "sentinel/CLAUDE.md", "fixtures/README.md")
    named = [root / name for name in names]
    return [p for p in named if p.is_file()] + sorted((root / "docs").rglob("*.md"))


def parse_markdown(text: str) -> Markdown:
    code: list[str] = []
    prose: list[str] = []
    fence = None
    for line in text.splitlines():
        opener = _FENCE.match(line)
        if fence is None and opener:
            fence = opener.group(1)
        elif fence is not None and opener and opener.group(1) == fence:
            fence = None
        else:
            (code if fence else prose).append(line)
    body = "\n".join(prose)
    code.extend(m.group(2) for m in _CODE_SPAN.finditer(body))
    links = [m.group(1) for m in _LINK.finditer(_CODE_SPAN.sub(" ", body))]
    return Markdown(tuple(code), tuple(links))


def load_claims(path: Path) -> list[Claim]:
    entries = tomllib.loads(path.read_text(encoding="utf-8"))["claim"]
    return [Claim(**{**entry, "patterns": tuple(entry["patterns"])}) for entry in entries]


# --- paths --------------------------------------------------------------------


def missing_paths(md: Markdown, doc_dir: Path, root: Path) -> list[str]:
    """Paths and relative links the document names that do not exist, in order."""
    top = _top_level_dirs(root)
    named = [(p, root) for p in _code_paths(md.code, top)]
    named += [(p, doc_dir) for p in _relative_links(md.links)]
    return _unique(p for p, base in named if not _exists(base, p, root))


def _top_level_dirs(root: Path) -> set[str]:
    return {
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and (not entry.name.startswith(".") or entry.name in TRACKED_HIDDEN)
    }


def _code_paths(code: Iterable[str], top: set[str]) -> Iterator[str]:
    for chunk in code:
        for word in chunk.split():
            candidate = _clean(word)
            if _is_repo_path(candidate, top):
                yield candidate


def _clean(word: str) -> str:
    word = word.strip("\"'(").rstrip("\"'),.;:!?")
    word = word.split("::", 1)[0]                 # a pytest node id names its file
    return re.sub(r"(\.\w+):[\w.-]+$", r"\1", word)  # so do file:line and file:function


def _is_repo_path(word: str, top: set[str]) -> bool:
    if "/" not in word or "://" in word or PLACEHOLDER.search(word):
        return False
    if word.split("/", 1)[0] not in top:
        return False
    return not any(word == p.rstrip("/") or word.startswith(p) for p in LOCAL_ONLY)


def _relative_links(links: Iterable[str]) -> Iterator[str]:
    for target in links:
        if _SCHEME.match(target) or target.startswith(("#", "//")):
            continue
        path = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if path:
            yield path


def _exists(base: Path, relative: str, root: Path) -> bool:
    if GLOB.search(relative):
        return bool(glob.glob(str(base / relative), recursive=True))
    resolved = (base / relative).resolve()
    return resolved.is_relative_to(root.resolve()) and resolved.exists()


# --- commands -----------------------------------------------------------------


def commands(md: Markdown) -> list[list[str]]:
    """Each shell command in the document's code, as argv, with `$`, env and `uv run` removed."""
    found = []
    for chunk in md.code:
        for line in chunk.splitlines():
            for segment in _SEPARATOR.split(_COMMENT.sub("", line)):
                argv = _strip_prefixes(segment.split())
                if argv:
                    found.append(argv)
    return found


def _strip_prefixes(words: list[str]) -> list[str]:
    i = 0
    while i < len(words):
        if words[i] in {"$", "exec", "time"} or _ENV_ASSIGNMENT.match(words[i]):
            i += 1
        elif words[i] == "uv" and words[i + 1 : i + 2] == ["run"]:
            i += 2
        else:
            break
    return words[i:]


def makefile_targets(makefile: str) -> set[str]:
    targets: set[str] = set()
    for line in makefile.splitlines():
        rule = _MAKE_RULE.match(line)
        if rule and not line.startswith("export "):
            targets.update(rule.group(1).split())
    return targets


def unknown_make_targets(argvs: Iterable[list[str]], targets: set[str]) -> list[str]:
    named = []
    for argv in argvs:
        if argv[0] != "make":
            continue
        for word in argv[1:]:
            if _ENV_ASSIGNMENT.match(word):
                continue
            if not _TARGET.match(word):
                break
            named.append(word)
    return _unique(t for t in named if t not in targets)


def cli_tree(parser: argparse.ArgumentParser) -> dict:
    """{subcommand: {sub-subcommand: ...}} read from the parser, not from --help text."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return {name: cli_tree(sub) for name, sub in action.choices.items()}
    return {}


def unknown_cli_commands(argvs: Iterable[list[str]], tree: dict) -> list[str]:
    unknown = []
    for argv in argvs:
        if argv[0] == "sentinel" or argv[0].endswith("bin/sentinel"):
            problem = _walk(argv[1:], tree)
            if problem:
                unknown.append(problem)
    return _unique(unknown)


def _walk(words: list[str], tree: dict) -> str | None:
    path: list[str] = []
    node = tree
    for word in words:
        if not node or not _SUBCOMMAND.match(word):
            return None
        path.append(word)
        if word not in node:
            return " ".join(path)
        node = node[word]
    return None


# --- packages -----------------------------------------------------------------


def undocumented_packages(package_root: Path) -> list[str]:
    """Directories of Python code under package_root without a docstring in __init__.py."""
    directories = {package_root, *(p.parent for p in package_root.rglob("*.py"))}
    problems = []
    for directory in sorted(d for d in directories if "__pycache__" not in d.parts):
        init = directory / "__init__.py"
        if not (init.is_file() and ast.get_docstring(ast.parse(init.read_text(encoding="utf-8")))):
            problems.append(directory.relative_to(package_root.parent).as_posix())
    return problems


# --- claims -------------------------------------------------------------------


def claim_problems(claim: Claim, root: Path) -> list[str]:
    if not (numbers_in_text(claim.quoted) or _DIGEST.search(claim.quoted)):
        return [f"{claim.quoted!r} states no number to check"]
    problems = []
    if _squash(claim.quoted) not in _squash(_read(root / claim.doc)):
        problems.append(f"{claim.doc} no longer says {claim.quoted!r}")
    source = _squash(_read(root / claim.source))
    problems += [f"{claim.source} no longer says {p!r}" for p in claim.patterns if _squash(p) not in source]
    unsupported = _ungrounded(claim.quoted, "\n".join(claim.patterns))
    if unsupported:
        problems.append(f"{claim.quoted!r} states {', '.join(unsupported)}, which {claim.source} does not")
    return problems


def _ungrounded(quoted: str, evidence: str) -> list[str]:
    """Numbers in `quoted` that `evidence` does not support. A digest must match verbatim."""
    digests = [d for d in _DIGEST.findall(quoted) if d not in _DIGEST.findall(evidence)]
    grounding = check_grounding(_DIGEST.sub(" ", quoted), _DIGEST.sub(" ", evidence))
    return digests + grounding.unsupported


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _squash(text: str) -> str:
    return " ".join(text.split())


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))
