"""Where each kind of evidence the model names can be found.

An index answers one question - does this locator point at something that
exists? - from text the repository already has:

    pytest     a node id in `pytest --collect-only -q` output (CI runs it)
    harness    a DDIL scenario marked PASS in docs/ddil-results.md, the
               generated report of a real two-node run (not re-run in CI)
    contract   an import-linter contract id in .importlinter (CI runs it)
    ci         a step name or job id in .github/workflows/ci.yml

A new kind of evidence is a new index; the trace does not change.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Protocol


class EvidenceIndex(Protocol):
    def resolves(self, locator: str) -> bool: ...


_NODE_ID = re.compile(r"^[^\s:][^:]*\.py::\S")   # path.py::name..., at column 0
_PARAMETRISED = re.compile(r"\[.*\]$")               # ids may contain spaces


@dataclasses.dataclass(frozen=True)
class PytestIds:
    ids: frozenset[str]

    @classmethod
    def from_collect_output(cls, text: str) -> PytestIds:
        """Node ids are the lines before the first blank one (then come
        warnings and the summary)."""
        ids = set()
        for line in text.splitlines():
            if not line.strip():
                break
            if _NODE_ID.match(line):
                ids.add(line.rstrip())
        functions = {_PARAMETRISED.sub("", node_id) for node_id in ids}
        return cls(frozenset(ids | functions))

    def resolves(self, locator: str) -> bool:
        return locator in self.ids


_SCENARIO_ROW = re.compile(r"^\|\s*([A-Z][A-Z_]*)\s*\|\s*(PASS|FAIL)\s*\|", re.M)


@dataclasses.dataclass(frozen=True)
class HarnessScenarios:
    passed: frozenset[str]

    @classmethod
    def from_report(cls, markdown: str) -> HarnessScenarios:
        return cls(frozenset(name for name, result in _SCENARIO_ROW.findall(markdown) if result == "PASS"))

    def resolves(self, locator: str) -> bool:
        return locator in self.passed


_CONTRACT = re.compile(r"^\[importlinter:contract:([^\]]+)\]\s*$", re.M)


@dataclasses.dataclass(frozen=True)
class ImportContracts:
    names: frozenset[str]

    @classmethod
    def from_config(cls, text: str) -> ImportContracts:
        return cls(frozenset(_CONTRACT.findall(text)))

    def resolves(self, locator: str) -> bool:
        return locator in self.names


_STEP_NAME = re.compile(r"^\s*-\s*name:\s*(.+?)\s*$", re.M)
_JOB_ID = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.M)


@dataclasses.dataclass(frozen=True)
class CiSteps:
    names: frozenset[str]

    @classmethod
    def from_workflow(cls, text: str) -> CiSteps:
        steps = {name.strip("\"'") for name in _STEP_NAME.findall(text)}
        _, _, jobs = text.partition("\njobs:\n")
        return cls(frozenset(steps | set(_JOB_ID.findall(jobs))))

    def resolves(self, locator: str) -> bool:
        return locator in self.names
