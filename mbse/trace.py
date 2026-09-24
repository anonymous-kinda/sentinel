"""Requirement -> satisfied by -> verified by -> status, and its Markdown.

The status is conservative:

    verified          at least one verification case, none planned, and every
                      piece of evidence they name resolves
    unverified        no verification case, or one is @Planned (not built yet)
    broken-reference  a non-planned case names evidence that does not resolve,
                      an unknown kind of evidence, or no evidence at all

Relations that name a requirement the model does not have, and cases that
verify nothing, are problems too. A trace with any problem is not ok.
"""

from __future__ import annotations

import collections
import dataclasses
import enum
import html
from collections.abc import Iterable, Mapping

from .evidence import EvidenceIndex
from .sysml import Evidence, Model, Requirement, VerificationCase


class Status(enum.StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    BROKEN = "broken-reference"


@dataclasses.dataclass(frozen=True)
class EvidenceLink:
    case: str
    kind: str
    locator: str
    planned: str | None
    exists: bool


@dataclasses.dataclass(frozen=True)
class Row:
    requirement: Requirement
    satisfied_by: tuple[str, ...]
    evidence: tuple[EvidenceLink, ...]
    status: Status

    @property
    def area(self) -> str:
        parts = self.requirement.id.split("-")
        return parts[1] if len(parts) == 3 else "OTHER"


@dataclasses.dataclass(frozen=True)
class PlannedCase:
    case: str
    milestone: str
    reason: str
    requirements: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Trace:
    rows: tuple[Row, ...]
    problems: tuple[str, ...]
    planned: tuple[PlannedCase, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems


def _lookup(requirements: Iterable[Requirement]) -> dict[str, str]:
    """A relation may name a requirement by its name or by its id."""
    lookup = {}
    for r in requirements:
        lookup[r.name] = r.id
        lookup[r.id] = r.id
    return lookup


def _unknown_parts(path: str, parts: frozenset[str]) -> list[str]:
    """Segments of `[Package::]a.b.c` that the model does not declare as parts."""
    chain = path.rsplit("::", 1)[-1]
    return [segment for segment in chain.split(".") if segment not in parts]


def _link(case: VerificationCase, evidence: Evidence, indexes: Mapping[str, EvidenceIndex]) -> EvidenceLink:
    index = indexes.get(evidence.kind)
    exists = index is not None and index.resolves(evidence.locator)
    return EvidenceLink(case.id, evidence.kind, evidence.locator, case.planned, exists)


def _case_problems(case: VerificationCase, links: list[EvidenceLink], kinds: Iterable[str]) -> list[str]:
    problems = [f"{case.id}: unknown evidence kind {link.kind!r}" for link in links if link.kind not in kinds]
    if not case.verifies:
        problems.append(f"{case.id}: verifies no requirement")
    if case.planned:
        return problems
    if not links:
        problems.append(f"{case.id}: claims to verify but names no evidence")
    problems += [
        f"{case.id}: {link.kind} evidence {link.locator!r} does not exist"
        for link in links
        if link.kind in kinds and not link.exists
    ]
    return problems


def _status(cases: list[VerificationCase], broken: set[str]) -> Status:
    if any(c.id in broken for c in cases):
        return Status.BROKEN
    if not cases or any(c.planned for c in cases):
        return Status.UNVERIFIED
    return Status.VERIFIED


def build_trace(model: Model, indexes: Mapping[str, EvidenceIndex]) -> Trace:
    lookup = _lookup(model.requirements)
    problems: list[str] = []

    satisfied_by: dict[str, set[str]] = collections.defaultdict(set)
    for relation in model.satisfactions:
        rid = lookup.get(relation.requirement)
        unknown = _unknown_parts(relation.by, model.parts)
        if rid is None:
            problems.append(f"satisfy names unknown requirement {relation.requirement!r} (by {relation.by})")
        elif unknown:
            problems.append(f"satisfy {relation.requirement} by {relation.by}: no part named {', '.join(unknown)}")
        else:
            satisfied_by[rid].add(relation.by)

    links: dict[str, list[EvidenceLink]] = {}
    broken: set[str] = set()
    cases_of: dict[str, list[VerificationCase]] = collections.defaultdict(list)
    for case in model.verifications:
        links[case.id] = [_link(case, e, indexes) for e in case.evidence]
        case_problems = _case_problems(case, links[case.id], indexes.keys())
        if case_problems:
            broken.add(case.id)
            problems += case_problems
        for target in case.verifies:
            rid = lookup.get(target)
            if rid is None:
                problems.append(f"{case.id}: verifies unknown requirement {target!r}")
                broken.add(case.id)
            else:
                cases_of[rid].append(case)

    rows = tuple(
        Row(
            requirement=r,
            satisfied_by=tuple(sorted(satisfied_by[r.id])),
            evidence=tuple(link for case in cases_of[r.id] for link in links[case.id]),
            status=_status(cases_of[r.id], broken),
        )
        for r in sorted(model.requirements, key=lambda r: r.id)
    )
    planned = tuple(
        PlannedCase(case.id, case.planned, case.reason, tuple(sorted({lookup[t] for t in case.verifies if t in lookup})))
        for case in sorted(model.verifications, key=lambda c: c.id)
        if case.planned
    )
    return Trace(rows, tuple(problems), planned)


# ---------------------------------------------------------------- rendering
LEGEND = """\
- **verified**: at least one verification case names the requirement, none of
  its cases is marked `@Planned`, and every piece of evidence they name exists:
  a pytest node id in `pytest --collect-only`, a DDIL harness scenario marked
  PASS in `docs/ddil-results.md`, an import-linter contract in `.importlinter`,
  or a step or job in `.github/workflows/ci.yml`. The trace checks that the
  evidence exists; CI runs the tests, the contracts and the steps. The harness
  report is the recorded run of a real two-node cluster and is not re-run in CI.
- **unverified**: no verification case yet, or a case is marked `@Planned`
  because its evidence is not built. Never counted as verified.
- **broken-reference**: evidence named without `@Planned` that does not exist.
  `make trace` exits non-zero and CI fails."""


def _cell(text: str) -> str:
    """Text shown as text: no HTML, and no pipe that would end the cell."""
    return html.escape(text, quote=False).replace("|", "\\|")


def _code(text: str) -> str:
    """A code span in a table cell: entities would show literally, so only the pipe is escaped."""
    return "`" + text.replace("|", "\\|") + "`"


def _evidence_line(link: EvidenceLink) -> str:
    line = f"{link.case}: {link.kind} {_code(link.locator)}"
    if link.planned:
        line += f" - planned ({link.planned})"
        if link.exists:
            line += ", now exists: link it and drop @Planned"
    elif not link.exists:
        line += " - **missing**"
    return line


def _summary(rows: tuple[Row, ...]) -> list[str]:
    counts: dict[str, collections.Counter[Status]] = collections.defaultdict(collections.Counter)
    for row in rows:
        counts[row.area][row.status] += 1
    total: collections.Counter[Status] = sum(counts.values(), collections.Counter())
    lines = ["| area | requirements | verified | unverified | broken-reference |", "|---|---|---|---|---|"]
    for area in sorted(counts):
        c = counts[area]
        lines.append(f"| {area} | {c.total()} | {c[Status.VERIFIED]} | {c[Status.UNVERIFIED]} | {c[Status.BROKEN]} |")
    lines.append(
        f"| **total** | **{total.total()}** | **{total[Status.VERIFIED]}** "
        f"| **{total[Status.UNVERIFIED]}** | **{total[Status.BROKEN]}** |"
    )
    return lines


PLANNED_NOTE = """\
Verification cases marked `@Planned` in `mbse/verification.sysml`. Their
locators name the evidence expected; when it lands, point the locator at it
and remove `@Planned`."""


def _planned_table(planned: tuple[PlannedCase, ...]) -> list[str]:
    lines = ["| case | milestone | verifies | not verified yet because |", "|---|---|---|---|"]
    for p in planned:
        lines.append(f"| {p.case} | {_cell(p.milestone)} | {'<br>'.join(p.requirements)} | {_cell(p.reason)} |")
    return lines


def _table(rows: tuple[Row, ...]) -> list[str]:
    lines = ["| id | requirement | satisfied by | verified by | status |", "|---|---|---|---|---|"]
    for row in rows:
        satisfied = "<br>".join(_code(p) for p in row.satisfied_by) or "(none)"
        verified = "<br>".join(_evidence_line(link) for link in row.evidence) or "(none)"
        lines.append(
            f"| {row.requirement.id} | {_cell(row.requirement.text)} | {satisfied} | {verified} | {row.status} |"
        )
    return lines


def render_markdown(trace: Trace) -> str:
    lines = [
        "# Requirements traceability",
        "",
        "Generated by `scripts/trace.py` (`make trace`) from the SysML v2 model in",
        "`mbse/`. Do not edit by hand: change the model and regenerate.",
        "",
        LEGEND,
        "",
        "## Summary",
        "",
        *_summary(trace.rows),
        "",
    ]
    if trace.problems:
        lines += ["## Problems", "", *(f"- {_cell(p)}" for p in trace.problems), ""]
    lines += ["## Requirements", "", *_table(trace.rows), ""]
    if trace.planned:
        lines += ["## Planned evidence", "", PLANNED_NOTE, "", *_planned_table(trace.planned), ""]
    return "\n".join(lines)
