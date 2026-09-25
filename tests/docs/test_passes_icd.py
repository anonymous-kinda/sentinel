"""docs/icd/passes-api.md against the unit validation behind its 422s.

PUT /api/passes/unit refuses a unit the node cannot compute for. The
bounds the document must state are formatted from the constants in
sentinel/passes/unit.py, so a bound that moves fails here until the
document moves with it.
"""

from sentinel.passes.unit import MAX_ALT_M, MAX_REACTION_TIME_MIN, MAX_UNIT_ID_CHARS, MIN_ALT_M

from .icd import ICD, section

PASSES_API = ICD / "passes-api.md"


def unit_bounds() -> list[str]:
    return [
        f"over {MAX_UNIT_ID_CHARS} characters",
        f"altitude outside [{MIN_ALT_M:g}, {MAX_ALT_M:g}] m",
        f"reaction time not positive or over {MAX_REACTION_TIME_MIN:g} min",
    ]


def unit_problems(doc: str) -> list[str]:
    unit = section(doc, "Unit")
    return [f"the unit bound {bound!r} is not stated" for bound in unit_bounds() if bound not in unit]


def test_the_unit_section_states_every_bound_the_code_enforces():
    assert unit_problems(PASSES_API.read_text()) == []


def test_a_stale_bound_is_caught():
    stale = PASSES_API.read_text().replace(f"{MAX_ALT_M:g}] m", "8849] m")
    assert unit_problems(stale) == [f"the unit bound 'altitude outside [{MIN_ALT_M:g}, {MAX_ALT_M:g}] m' is not stated"]
