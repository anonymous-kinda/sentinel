"""Wire the repository into a trace: `scripts/trace.py` calls main().

    exit 0   every reference resolves; docs/traceability.md written
    exit 1   the trace has problems; the file is still written and lists them
    exit 2   the trace could not be built (unreadable model, pytest collection failed)
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from collections.abc import Callable

from sentinel.obs import get_logger

from .evidence import CiSteps, EvidenceIndex, HarnessScenarios, ImportContracts, PytestIds
from .sysml import ModelError, read_model_dir
from .trace import Status, Trace, build_trace, render_markdown

log = get_logger(__name__)

ROOT = pathlib.Path(__file__).resolve().parent.parent
DDIL_REPORT = "docs/ddil-results.md"
IMPORT_CONTRACTS = ".importlinter"
CI_WORKFLOW = ".github/workflows/ci.yml"


class CollectionFailed(RuntimeError):
    """`pytest --collect-only` did not complete, so no test id can be checked."""


def collect_pytest(root: pathlib.Path) -> str:
    """The node ids pytest would run, from `pytest --collect-only -q` (offline)."""
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
    done = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-5:])
        raise CollectionFailed(f"pytest --collect-only exited {done.returncode}: {tail}")
    return done.stdout


def _source(root: pathlib.Path, relative: str) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("Evidence source missing", path=str(path))
        return ""


def repository_indexes(root: pathlib.Path, collect_output: str) -> dict[str, EvidenceIndex]:
    return {
        "pytest": PytestIds.from_collect_output(collect_output),
        "harness": HarnessScenarios.from_report(_source(root, DDIL_REPORT)),
        "contract": ImportContracts.from_config(_source(root, IMPORT_CONTRACTS)),
        "ci": CiSteps.from_workflow(_source(root, CI_WORKFLOW)),
    }


def generate(root: pathlib.Path, collect_output: str) -> Trace:
    model = read_model_dir(root / "mbse")
    return build_trace(model, repository_indexes(root, collect_output))


def _report(trace: Trace, out: pathlib.Path) -> None:
    statuses = [row.status for row in trace.rows]
    log.info(
        "Trace written",
        path=str(out),
        requirements=len(statuses),
        verified=statuses.count(Status.VERIFIED),
        unverified=statuses.count(Status.UNVERIFIED),
        broken=statuses.count(Status.BROKEN),
    )
    for problem in trace.problems:
        log.error("Trace problem", problem=problem)
    ready = {link for row in trace.rows for link in row.evidence if link.planned and link.exists}
    for link in sorted(ready, key=lambda link: (link.case, link.locator)):
        log.warning("Planned evidence now exists", case=link.case, kind=link.kind, locator=link.locator)


def main(
    root: pathlib.Path = ROOT,
    out: pathlib.Path | None = None,
    collect: Callable[[pathlib.Path], str] = collect_pytest,
) -> int:
    out = out or root / "docs" / "traceability.md"
    try:
        trace = generate(root, collect(root))
    except (ModelError, CollectionFailed) as error:
        log.error("Trace not generated", error=str(error))
        return 2
    out.write_text(render_markdown(trace), encoding="utf-8")
    _report(trace, out)
    return 0 if trace.ok else 1
