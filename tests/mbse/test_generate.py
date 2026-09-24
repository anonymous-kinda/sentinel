"""scripts/trace.py: read the model, find the evidence, write the trace.

Exit codes: 0 every reference resolves, 1 the trace has problems (the file
is still written so it explains them), 2 the trace could not be built.
"""

import logging
import textwrap

import pytest

from mbse.generate import CollectionFailed, collect_pytest, main

MODEL = """
package P {
    requirement <'REQ-DDIL-001'> consoleWhileDenied {
        doc /* The console answers while the link is DENIED. */
    }
    part edge;
    satisfy consoleWhileDenied by edge;
    verification <'VC-DDIL-001'> vc {
        objective { verify consoleWhileDenied; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/a.py::test_a"; }
        @Evidence { kind = EvidenceKind::harness; locator = "DENIED"; }
        @Evidence { kind = EvidenceKind::contract; locator = "ai-does-no-math"; }
        @Evidence { kind = EvidenceKind::ci; locator = "Lint"; }
    }
}
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "mbse").mkdir()
    (tmp_path / "mbse" / "model.sysml").write_text(MODEL)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ddil-results.md").write_text("| DENIED | PASS | 11/11 | 2026-09-24T02:39Z |\n")
    (tmp_path / ".importlinter").write_text("[importlinter:contract:ai-does-no-math]\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("jobs:\n  python:\n    steps:\n      - name: Lint\n")
    return tmp_path


def collected(*ids):
    return lambda root: "\n".join(ids) + "\n"


def test_writes_the_trace_and_exits_zero_when_every_reference_resolves(repo, caplog):
    out = repo / "docs" / "traceability.md"
    with caplog.at_level(logging.INFO):
        assert main(repo, out, collected("tests/a.py::test_a")) == 0
    text = out.read_text()
    assert "| REQ-DDIL-001 |" in text and "| verified |" in text
    written = next(r for r in caplog.records if r.getMessage() == "Trace written")
    assert written.fields["requirements"] == 1
    assert written.fields["verified"] == 1


def test_a_broken_reference_exits_one_and_the_file_says_why(repo, caplog):
    out = repo / "docs" / "traceability.md"
    with caplog.at_level(logging.INFO):
        assert main(repo, out, collected("tests/a.py::test_renamed")) == 1
    assert "tests/a.py::test_a" in out.read_text()
    problem = next(r for r in caplog.records if r.getMessage() == "Trace problem")
    assert "tests/a.py::test_a" in problem.fields["problem"]


def test_a_missing_evidence_source_breaks_the_references_that_need_it(repo, caplog):
    (repo / "docs" / "ddil-results.md").unlink()
    with caplog.at_level(logging.INFO):
        assert main(repo, repo / "out.md", collected("tests/a.py::test_a")) == 1
    missing = next(r for r in caplog.records if r.getMessage() == "Evidence source missing")
    assert missing.fields["path"].endswith("ddil-results.md")


def test_an_unreadable_model_exits_two_and_writes_nothing(repo, caplog):
    (repo / "mbse" / "model.sysml").write_text("package P { requirement noId { doc /* x */ } }")
    out = repo / "out.md"
    with caplog.at_level(logging.INFO):
        assert main(repo, out, collected("tests/a.py::test_a")) == 2
    assert not out.exists()
    assert any(r.getMessage() == "Trace not generated" for r in caplog.records)


def test_planned_evidence_that_now_exists_is_logged_as_a_warning(repo, caplog):
    model = MODEL.replace("objective {", '@Planned { milestone = "M3"; }\n        objective {')
    (repo / "mbse" / "model.sysml").write_text(model)
    with caplog.at_level(logging.INFO):
        assert main(repo, repo / "out.md", collected("tests/a.py::test_a")) == 0
    ready = [r for r in caplog.records if r.getMessage() == "Planned evidence now exists"]
    assert {r.fields["locator"] for r in ready} >= {"tests/a.py::test_a"}
    assert all(r.levelno == logging.WARNING for r in ready)


def test_collect_pytest_raises_when_collection_fails(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_broken.py").write_text(textwrap.dedent("def test_x(:\n    pass\n"))
    with pytest.raises(CollectionFailed):
        collect_pytest(tmp_path)
