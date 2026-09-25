"""`make compliance` after editing a control source passes the first time.

The suite checks that the committed SSP and component definition are what the
sources generate. If the tests ran before those documents were regenerated,
every source edit would fail its own run and file the staleness as a POA&M item.
"""

from tests.makefile import dry_run

GENERATOR = "scripts/oscal_evidence.py"


def _step(recipe: list[str], matches) -> int:
    found = [i for i, line in enumerate(recipe) if matches(line)]
    assert found, "make compliance has no such step"
    return found[0]


def _pytest(line: str) -> bool:
    return "pytest" in line


def _authored_only(line: str) -> bool:
    return GENERATOR in line and "--junit" not in line


def _with_evidence(line: str) -> bool:
    return GENERATOR in line and "--junit" in line


def test_authored_documents_are_regenerated_before_the_tests_run():
    recipe = dry_run("compliance")
    assert _step(recipe, _authored_only) < _step(recipe, _pytest)


def test_the_evidence_run_still_follows_the_tests():
    recipe = dry_run("compliance")
    assert _step(recipe, _pytest) < _step(recipe, _with_evidence)
