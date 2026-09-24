"""Where each kind of evidence the model names can be found.

Every index answers one question - does this locator point at something
that exists? - from text the repository already has, so the trace needs no
network and no running cluster.
"""

from mbse.evidence import CiSteps, HarnessScenarios, ImportContracts, PytestIds

COLLECT_OUTPUT = """\
tests/test_tier1_geometry.py::test_known_state_produces_known_rtn_basis
tests/test_tier3_cara_validation.py::test_pc2d_matches_published_cara_value[HST-DELTA]
tests/test_tier3_cara_validation.py::test_pc2d_matches_published_cara_value[TERRA-IRIDIUM]
tests/property/test_crdt.py::TestDDILNetwork::runTest
tests/test_cdm_codec.py::test_wrong_messages_are_rejected[X-X = 7000.0 [m]-1-WRONG_UNIT]

=============================== warnings summary ===============================
tests/test_x.py::test_warned
  /path/to/module.py:12: DeprecationWarning: see tests/y.py::test_z

428 tests collected in 2.95s
"""


def test_pytest_ids_match_exact_ids_and_parametrised_functions():
    ids = PytestIds.from_collect_output(COLLECT_OUTPUT)
    assert ids.resolves("tests/test_tier1_geometry.py::test_known_state_produces_known_rtn_basis")
    assert ids.resolves("tests/test_tier3_cara_validation.py::test_pc2d_matches_published_cara_value")
    assert ids.resolves("tests/test_tier3_cara_validation.py::test_pc2d_matches_published_cara_value[HST-DELTA]")
    assert ids.resolves("tests/property/test_crdt.py::TestDDILNetwork::runTest")
    # Parametrise ids may contain spaces.
    assert ids.resolves("tests/test_cdm_codec.py::test_wrong_messages_are_rejected")
    assert ids.resolves("tests/test_cdm_codec.py::test_wrong_messages_are_rejected[X-X = 7000.0 [m]-1-WRONG_UNIT]")


def test_pytest_ids_do_not_match_prefixes_files_or_the_summary_line():
    ids = PytestIds.from_collect_output(COLLECT_OUTPUT)
    assert not ids.resolves("tests/y.py::test_z")    # mentioned inside a warning, not collected
    assert not ids.resolves("tests/test_tier1_geometry.py::test_known_state")
    assert not ids.resolves("tests/test_tier1_geometry.py")
    assert not ids.resolves("tests/test_tier3_cara_validation.py::test_pc2d_matches_published_cara_value[OTHER]")
    assert not ids.resolves("428 tests collected in 2.95s")


REPORT = """\
| scenario | result | assertions | ran |
|---|---|---|---|
| DENIED | PASS | 11/11 | 2026-09-24T02:39Z |
| LIMITED | FAIL | 2/3 | 2026-09-24T02:40Z |

## DENIED

- PASS - edge console stays available while denied (p95 < 200 ms)
"""


def test_a_harness_scenario_resolves_only_if_the_generated_report_says_it_passed():
    scenarios = HarnessScenarios.from_report(REPORT)
    assert scenarios.resolves("DENIED")
    assert not scenarios.resolves("LIMITED")        # ran, but failed: not evidence
    assert not scenarios.resolves("OPSEC")          # never ran


IMPORTLINTER = """\
[importlinter]
root_package = sentinel

[importlinter:contract:ai-does-no-math]
name = The AI layer has no path to the maths
type = forbidden
"""


def test_import_contracts_resolve_by_their_id():
    contracts = ImportContracts.from_config(IMPORTLINTER)
    assert contracts.resolves("ai-does-no-math")
    assert not contracts.resolves("importlinter")
    assert not contracts.resolves("The AI layer has no path to the maths")


WORKFLOW = """\
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  python:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - name: Module boundaries (MOSA interfaces)
        run: uv run lint-imports
      - name: "Quoted step name"
        run: true
  secrets:
    runs-on: ubuntu-24.04
"""


def test_ci_evidence_resolves_to_step_names_and_job_ids_only():
    ci = CiSteps.from_workflow(WORKFLOW)
    assert ci.resolves("Module boundaries (MOSA interfaces)")
    assert ci.resolves("Quoted step name")
    assert ci.resolves("secrets")
    assert ci.resolves("python")
    assert not ci.resolves("push")                  # a trigger, not a job
    assert not ci.resolves("uv run lint-imports")   # a command, not a step name
