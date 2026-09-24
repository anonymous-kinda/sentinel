"""Resolve every citation in the authored sources against the repository.

The SSP may only cite evidence that exists: a file on disk, a test function
pytest can collect, a job in a workflow, a DDIL harness scenario. Tests are
resolved statically (AST), so this runs in milliseconds and needs no
collection. A class bound by assignment (hypothesis's `Machine.TestCase`)
cannot be inspected statically; any method cited on it is accepted.
"""

from __future__ import annotations

import ast
import functools
import pathlib
import re

from .sources import Sources

_JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")


def unresolved(sources: Sources, root: pathlib.Path) -> list[str]:
    problems = []
    scenarios = _harness_scenarios(root)
    for control in sources.controls:
        for contribution in control.contributions:
            problems += [f"{control.id}: {p}" for p in _contribution_problems(contribution, root, scenarios)]
    for method in sources.system.assessments:
        problems += [f"assessment {method.key}: CI job {j} does not exist" for j in method.ci if not _job_exists(j, root)]
    for path in (sources.stig.xccdf, sources.stig.cci_list, sources.stig.role):
        if not (root / path).exists():
            problems.append(f"stig.toml: {path} does not exist")
    return problems


def _contribution_problems(contribution, root: pathlib.Path, scenarios: set[str]) -> list[str]:
    problems = [f"file {f} does not exist" for f in contribution.files if not (root / f).exists()]
    problems += [p for t in contribution.tests if (p := _test_problem(t, root))]
    problems += [f"CI job {j} does not exist" for j in contribution.ci if not _job_exists(j, root)]
    problems += [f"harness scenario {s} does not exist" for s in contribution.harness if s not in scenarios]
    return problems


def _test_problem(citation: str, root: pathlib.Path) -> str | None:
    path, _, rest = citation.partition("::")
    if not (root / path).is_file():
        return f"test file {path} does not exist"
    if rest and not _defined(_module_names(root / path), rest.split("::")):
        return f"{citation} is not defined"
    return None


def _defined(names: dict[str, set[str] | None], parts: list[str]) -> bool:
    if parts[0] not in names:
        return False
    if len(parts) == 1:
        return True
    methods = names[parts[0]]
    return methods is None or parts[1] in methods


@functools.cache
def _module_names(path: pathlib.Path) -> dict[str, set[str] | None]:
    """Top-level functions (no members), classes (their methods), assigned names (unknown members)."""
    names: dict[str, set[str] | None] = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names[node.name] = set()
        elif isinstance(node, ast.ClassDef):
            names[node.name] = {n.name for n in node.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
        elif isinstance(node, ast.Assign):
            names.update({t.id: None for t in node.targets if isinstance(t, ast.Name)})
    return names


def _job_exists(citation: str, root: pathlib.Path) -> bool:
    workflow, _, job = citation.partition("#")
    path = root / ".github" / "workflows" / workflow
    if not path.is_file():
        return False
    lines = path.read_text().splitlines()
    start = next((i for i, line in enumerate(lines) if line.rstrip() == "jobs:"), None)
    return start is not None and any(
        (m := _JOB.match(line)) and m.group(1) == job for line in lines[start + 1 :]
    )


def _harness_scenarios(root: pathlib.Path) -> set[str]:
    path = root / "harness" / "scenarios.py"
    if not path.is_file():
        return set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SCENARIOS" for t in node.targets):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return set()
