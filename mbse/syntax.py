"""Check the model against the full SysML v2 textual grammar.

The grammar is the OMG SysML v2 pilot implementation's Xtext grammar as
ported to textX by sysml2py (LGPL-3.0 grammar, MIT package); it is not
vendored here. `make sysml-check` runs this in an isolated environment:

    uv run --no-project --isolated --with sysml2py==0.5.3 --with 'setuptools<81' \
        python scripts/sysml_check.py mbse/*.sysml

What it proves: every file parses under that grammar. What it does not:
name resolution, typing or any other semantic rule - the port is syntax
only, and is more permissive than the pilot in places. The trace reader
(mbse/sysml.py) separately rejects the relations it cannot resolve.

A validator that accepts KNOWN_BAD has checked nothing, so it is refused
before any model file is read.
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import importlib.util
import pathlib
from collections.abc import Callable, Sequence
from typing import Protocol

from sentinel.obs import get_logger

log = get_logger(__name__)

KNOWN_BAD = "package Control { part def A part def B; }"   # missing ';' after A
MESSAGE_LIMIT = 200


class SysmlSyntaxError(Exception):
    def __init__(self, line: int, col: int, message: str):
        super().__init__(f"{line}:{col}: {message}")
        self.line, self.col, self.message = line, col, message


class ValidatorUntrustworthy(RuntimeError):
    """The validator accepted a model that is not valid SysML v2."""


class Parser(Protocol):
    def parse(self, text: str) -> None:
        """Return if the text parses; raise SysmlSyntaxError otherwise."""


@dataclasses.dataclass(frozen=True)
class SyntaxProblem:
    path: str
    line: int
    col: int
    message: str


def _require_rejects_known_bad(parser: Parser) -> None:
    try:
        parser.parse(KNOWN_BAD)
    except SysmlSyntaxError:
        return
    raise ValidatorUntrustworthy("the validator accepted a known-bad model")


def check(paths: Sequence[pathlib.Path], parser: Parser) -> list[SyntaxProblem]:
    _require_rejects_known_bad(parser)
    problems = []
    for path in paths:
        try:
            parser.parse(path.read_text(encoding="utf-8"))
        except SysmlSyntaxError as error:
            problems.append(SyntaxProblem(str(path), error.line, error.col, error.message[:MESSAGE_LIMIT]))
    return problems


class PilotGrammar:
    """textX over the pilot grammar shipped inside the sysml2py package."""

    def __init__(self) -> None:
        from textx import metamodel_from_file  # present only in the isolated environment

        spec = importlib.util.find_spec("sysml2py")   # locate, without importing astropy
        if spec is None or not spec.submodule_search_locations:
            raise ModuleNotFoundError("No module named 'sysml2py'")
        grammar = pathlib.Path(spec.submodule_search_locations[0]) / "grammar" / "SysML_compiled.tx"
        self._meta = metamodel_from_file(str(grammar), memoization=True)
        self.version = f"sysml2py {importlib.metadata.version('sysml2py')}"

    def parse(self, text: str) -> None:
        from textx import TextXSyntaxError

        try:
            self._meta.model_from_str(text)
        except TextXSyntaxError as error:
            raise SysmlSyntaxError(error.line, error.col, str(error.message)) from error


def main(argv: Sequence[str], parser_factory: Callable[[], Parser] = PilotGrammar) -> int:
    paths = [pathlib.Path(arg) for arg in argv]
    if not paths:
        log.error("SysML syntax check given no files")
        return 2
    try:
        parser = parser_factory()
    except ModuleNotFoundError as error:
        log.error("SysML validator not installed", error=str(error))
        return 2
    try:
        problems = check(paths, parser)
    except ValidatorUntrustworthy as error:
        log.error("SysML validator not trusted", error=str(error))
        return 2
    for problem in problems:
        log.error("SysML syntax error", path=problem.path, line=problem.line, col=problem.col, message=problem.message)
    validator = getattr(parser, "version", type(parser).__name__)
    log.info("SysML syntax checked", files=len(paths), errors=len(problems), validator=validator)
    return 1 if problems else 0
