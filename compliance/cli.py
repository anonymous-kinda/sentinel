"""Generate the OSCAL package: authored documents always, assessment documents from evidence.

    python scripts/oscal_evidence.py                       # profile, component definition, SSP, AP
    python scripts/oscal_evidence.py --junit build/compliance/junit.xml \\
        [--harness harness/results] [--xccdf stig-results.xml]   # + assessment results, POA&M

Exit status 2 means nothing trustworthy could be generated (a source that
misstates the system, or evidence that cannot be read); the reason is logged.
Failing tests do not fail the generator: they are what the POA&M is for.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from sentinel.obs import get_logger

from . import assessment, authored, oscal_common
from .citations import unresolved
from .evidence import collect
from .inputs import EvidenceError, read_harness, read_junit, read_xccdf
from .sources import SourceError, Sources, load_sources
from .stig import load_stig_catalog

log = get_logger(__name__)
ROOT = pathlib.Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _generate(args)
    except (SourceError, EvidenceError) as exc:
        log.error("Compliance generation failed", kind=type(exc).__name__, error=str(exc))
        return 2
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT, help="repository root (citations resolve here)")
    parser.add_argument("--sources", type=pathlib.Path, help="authored sources (default: <root>/compliance/sources)")
    parser.add_argument("--workspace", type=pathlib.Path, help="trestle workspace (default: <root>/compliance/oscal)")
    parser.add_argument("--junit", type=pathlib.Path, help="pytest --junitxml output")
    parser.add_argument("--harness", type=pathlib.Path, help="DDIL harness results directory")
    parser.add_argument("--xccdf", type=pathlib.Path, help="OpenSCAP XCCDF results from the STIG role's scan")
    return parser


def _generate(args: argparse.Namespace) -> None:
    root = args.root
    workspace = args.workspace or root / "compliance" / "oscal"
    if (args.harness or args.xccdf) and not args.junit:
        raise EvidenceError("--harness and --xccdf add to a test run; pass the run's --junit XML too")
    sources = _checked_sources(args.sources or root / "compliance" / "sources", root)
    documents = {
        oscal_common.PROFILE: authored.build_profile(sources),
        oscal_common.COMPONENT_DEFINITION: authored.build_component_definition(sources),
        oscal_common.SSP: authored.build_ssp(sources),
        oscal_common.ASSESSMENT_PLAN: authored.build_assessment_plan(sources),
    }
    assessed, summary = _assessed(sources, args, root) if args.junit else ({}, None)
    _write(workspace, {**documents, **assessed})
    log.info("Authored documents written", workspace=str(workspace), documents=len(documents))
    if summary:
        log.info("Assessment documents written", **summary)


def _checked_sources(directory: pathlib.Path, root: pathlib.Path) -> Sources:
    sources = load_sources(directory)
    problems = unresolved(sources, root)
    if problems:
        raise SourceError("citations do not resolve: " + "; ".join(problems))
    return sources


def _assessed(
    sources: Sources, args: argparse.Namespace, root: pathlib.Path
) -> tuple[dict[str, Any], dict[str, int]]:
    evidence = collect(
        sources,
        read_junit(args.junit),
        harness=read_harness(args.harness) if args.harness else None,
        scan=read_xccdf(args.xccdf) if args.xccdf else None,
    )
    try:
        stig = load_stig_catalog(root, sources.stig)
    except ValueError as exc:
        raise SourceError(f"stig.toml: {exc}") from exc
    results = assessment.build_assessment_results(sources, evidence, stig)
    poam = assessment.build_poam(sources, evidence, stig)
    (result,) = results["assessment-results"]["results"]
    summary = {
        "controls": len(evidence.controls),
        "observed": sum(e.observed for e in evidence.controls),
        "satisfied": sum(e.satisfied for e in evidence.controls),
        "findings": len(result.get("findings", [])),
        "poam_items": len(poam["plan-of-action-and-milestones"]["poam-items"]),
    }
    return {oscal_common.ASSESSMENT_RESULTS: results, oscal_common.POAM: poam}, summary


def _write(workspace: pathlib.Path, documents: dict[str, Any]) -> None:
    for relative, document in documents.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
