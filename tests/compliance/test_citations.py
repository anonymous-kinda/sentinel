"""Every piece of evidence the SSP cites must exist in the repository.

Checked against a small synthetic repository so each kind of dangling
citation is shown to be caught.
"""

import dataclasses
import pathlib

import pytest

from compliance.citations import unresolved
from compliance.sources import load_sources

DATA = pathlib.Path(__file__).parent / "data"


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_x():\n    pass\n\n\nclass TestMachine:\n    def runTest(self):\n        pass\n\n\nTestAlias = TestMachine\n"
    )
    (tmp_path / "sentinel").mkdir()
    (tmp_path / "sentinel" / "code.py").write_text("")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(
        "name: ci\non: push\njobs:\n  python:\n    runs-on: x\n    steps: []\n  infra:\n    runs-on: x\n"
    )
    (tmp_path / ".github" / "workflows" / "harness.yml").write_text("jobs:\n  scenario:\n    runs-on: x\n")
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "scenarios.py").write_text('SCENARIOS = {\n    "denied": denied,\n    "limited": limited,\n}\n')
    for vendored in ("vendor/stig.xml", "vendor/cci.zip"):
        (tmp_path / vendored).parent.mkdir(exist_ok=True)
        (tmp_path / vendored).write_text("")
    (tmp_path / "roles" / "stig").mkdir(parents=True)
    return tmp_path


def sources_citing(**evidence):
    """Fixture sources with one contribution citing exactly `evidence`."""
    sources = load_sources(DATA / "sources")
    control = sources.controls[0]
    contribution = dataclasses.replace(
        control.contributions[0], **{"tests": (), "harness": (), "ci": (), "files": (), **evidence}
    )
    stig = dataclasses.replace(sources.stig, xccdf="vendor/stig.xml", cci_list="vendor/cci.zip", role="roles/stig")
    return dataclasses.replace(
        sources, controls=(dataclasses.replace(control, contributions=(contribution,)),), stig=stig
    )


def test_resolvable_citations_report_nothing(repo):
    sources = sources_citing(
        tests=("tests/test_a.py::test_x", "tests/test_a.py::TestMachine::runTest", "tests/test_a.py::TestMachine",
               "tests/test_a.py"),
        harness=("denied",),
        ci=("ci.yml#python", "ci.yml#infra"),
        files=("sentinel/code.py",),
    )
    assert unresolved(sources, repo) == []


@pytest.mark.parametrize(
    ("evidence", "problem"),
    [
        ({"files": ("sentinel/gone.py",)}, "si-10: file sentinel/gone.py does not exist"),
        ({"tests": ("tests/test_b.py::test_x",)}, "si-10: test file tests/test_b.py does not exist"),
        ({"tests": ("tests/test_a.py::test_y",)}, "si-10: tests/test_a.py::test_y is not defined"),
        ({"tests": ("tests/test_a.py::TestMachine::test_z",)}, "si-10: tests/test_a.py::TestMachine::test_z is not defined"),
        ({"ci": ("ci.yml#web",)}, "si-10: CI job ci.yml#web does not exist"),
        ({"ci": ("release.yml#build",)}, "si-10: CI job release.yml#build does not exist"),
        ({"harness": ("sunny",)}, "si-10: harness scenario sunny does not exist"),
    ],
)
def test_each_kind_of_dangling_citation_is_reported(repo, evidence, problem):
    assert unresolved(sources_citing(**evidence), repo) == [problem]


def test_missing_stig_inputs_are_reported(repo):
    (repo / "vendor" / "cci.zip").unlink()
    assert unresolved(sources_citing(), repo) == ["stig.toml: vendor/cci.zip does not exist"]


def test_assessment_methods_cite_real_ci_jobs(repo):
    sources = sources_citing()
    ladder = dataclasses.replace(sources.system.assessments[0], ci=("ci.yml#pytest",))
    system = dataclasses.replace(sources.system, assessments=(ladder, *sources.system.assessments[1:]))
    assert unresolved(dataclasses.replace(sources, system=system), repo) == [
        "assessment ladder: CI job ci.yml#pytest does not exist"
    ]
