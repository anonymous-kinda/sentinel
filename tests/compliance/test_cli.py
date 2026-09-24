"""The generator end to end: sources and evidence in, workspace documents out."""

import json
import logging
import pathlib

import pytest

from compliance.cli import main

DATA = pathlib.Path(__file__).parent / "data"
ROOT = pathlib.Path(__file__).resolve().parents[2]
AUTHORED = [
    "profiles/sentinel/profile.json",
    "component-definitions/sentinel/component-definition.json",
    "system-security-plans/sentinel/system-security-plan.json",
    "assessment-plans/sentinel/assessment-plan.json",
]
ASSESSED = [
    "assessment-results/sentinel/assessment-results.json",
    "plan-of-action-and-milestones/sentinel/plan-of-action-and-milestones.json",
]


def args(workspace, *extra):
    return ["--root", str(ROOT), "--sources", str(DATA / "sources"), "--workspace", str(workspace), *extra]


def fields(caplog, message):
    return [getattr(r, "fields", {}) for r in caplog.records if r.getMessage() == message]


def test_without_evidence_only_the_authored_documents_are_written(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    assert main(args(tmp_path)) == 0
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.json")) == sorted(AUTHORED)
    assert fields(caplog, "Authored documents written") == [{"workspace": str(tmp_path), "documents": 4}]


def test_with_evidence_results_and_poam_are_written_too(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    code = main(args(
        tmp_path,
        "--junit", str(DATA / "junit_mixed.xml"),
        "--harness", str(DATA / "harness"),
        "--xccdf", str(DATA / "xccdf_results.xml"),
    ))
    assert code == 0
    for rel in AUTHORED + ASSESSED:
        assert json.loads((tmp_path / rel).read_text())
    (summary,) = fields(caplog, "Assessment documents written")
    assert summary == {"controls": 3, "observed": 2, "satisfied": 1, "findings": 1, "poam_items": 9}


def test_documents_end_with_a_newline_and_are_stable_across_runs(tmp_path):
    main(args(tmp_path))
    first = {rel: (tmp_path / rel).read_text() for rel in AUTHORED}
    main(args(tmp_path))
    assert first == {rel: (tmp_path / rel).read_text() for rel in AUTHORED}
    assert all(text.endswith("}\n") for text in first.values())


def test_unreadable_evidence_fails_the_run_and_says_why(tmp_path, caplog):
    bad = tmp_path / "junit.xml"
    bad.write_text("<testsuites")
    assert main(args(tmp_path / "out", "--junit", str(bad))) == 2
    (failure,) = fields(caplog, "Compliance generation failed")
    assert failure["kind"] == "EvidenceError" and "not well-formed" in failure["error"]
    assert not (tmp_path / "out" / ASSESSED[0]).exists()


def test_a_dangling_citation_fails_before_anything_is_written(tmp_path, caplog):
    sources = tmp_path / "sources"
    sources.mkdir()
    for name in ("system.toml", "stig.toml"):
        (sources / name).write_text((DATA / "sources" / name).read_text())
    text = (DATA / "sources" / "controls.toml").read_text()
    (sources / "controls.toml").write_text(text.replace("sentinel/cdm/validate.py", "sentinel/cdm/gone.py"))
    code = main(["--root", str(ROOT), "--sources", str(sources), "--workspace", str(tmp_path / "out")])
    assert code == 2
    (failure,) = fields(caplog, "Compliance generation failed")
    assert failure["kind"] == "SourceError"
    assert "si-10: file sentinel/cdm/gone.py does not exist" in failure["error"]
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("flag", ["--harness", "--xccdf"])
def test_harness_or_scan_evidence_needs_a_junit_run(tmp_path, flag, caplog):
    assert main(args(tmp_path, flag, str(DATA / "harness"))) == 2
    (failure,) = fields(caplog, "Compliance generation failed")
    assert "--junit" in failure["error"]
