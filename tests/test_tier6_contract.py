"""Tier 6 - the output contract.

Design principle 2 is that the maths is auditable. These tests enforce the
structural guarantees that make that true: a probability never travels
without the method that produced it, a dilution flag never travels without
the bound it implies, and every result is traceable to its inputs.

Rungs 24-26 of the ladder.
"""

import numpy as np
import pytest

from sentinel.risk.engine import assess
from sentinel.risk.types import Method, RefusalReason

from .conftest import make_conjunction

pytestmark = pytest.mark.tier6


# --- rung 24 --------------------------------------------------------------
@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c,
        lambda c: c.replace(secondary=c.secondary.replace(covariance_rtn_m2=None)),
        lambda c: c.replace(primary=c.primary.replace(radius_m=None)),
        lambda c: c.replace(
            secondary=c.secondary.replace(velocity_km_s=c.primary.velocity_km_s.copy())
        ),
    ],
)
def test_pc_never_travels_without_method(mutate):
    result = assess(mutate(make_conjunction(miss_m=100.0, sigma_m=50.0)))

    assert result.method in (Method.FOSTER_ESTES_2D, Method.REFUSED)
    if result.method is Method.REFUSED:
        assert result.pc is None
        assert result.refusal_reason is not None
        assert isinstance(result.refusal_reason, RefusalReason)
    else:
        assert result.pc is not None
        assert result.refusal_reason is None


# --- rung 25 --------------------------------------------------------------
def test_dilution_flag_implies_pc_max_is_populated():
    for sigma in (30.0, 100.0, 400.0, 2000.0):
        result = assess(make_conjunction(miss_m=1000.0, sigma_m=sigma, radius_m=0.5))
        if result.dilution_flag:
            assert result.pc_max is not None
            assert result.pc_max >= result.pc


# --- rung 26 --------------------------------------------------------------
def test_inputs_hash_is_stable_across_runs():
    a = assess(make_conjunction(miss_m=100.0, sigma_m=50.0))
    b = assess(make_conjunction(miss_m=100.0, sigma_m=50.0))
    assert a.inputs_hash == b.inputs_hash


def test_inputs_hash_changes_when_any_input_changes():
    base = make_conjunction(miss_m=100.0, sigma_m=50.0)
    base_hash = assess(base).inputs_hash

    variants = {
        "miss": make_conjunction(miss_m=100.001, sigma_m=50.0),
        "sigma": make_conjunction(miss_m=100.0, sigma_m=50.001),
        "radius": make_conjunction(miss_m=100.0, sigma_m=50.0, radius_m=5.001),
    }
    for name, variant in variants.items():
        assert assess(variant).inputs_hash != base_hash, f"{name} did not change the hash"


def test_refusals_also_carry_an_inputs_hash():
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    no_cov = conj.replace(secondary=conj.secondary.replace(covariance_rtn_m2=None))

    result = assess(no_cov)

    assert result.method is Method.REFUSED
    assert result.inputs_hash
    assert len(result.inputs_hash) == 64  # sha256 hex


def test_diagnostics_record_the_independence_assumption():
    """Combining covariances additively assumes uncorrelated orbit
    determinations. The assumption is recorded, not buried."""
    result = assess(make_conjunction(miss_m=100.0, sigma_m=50.0))
    assert result.diagnostics["independence_assumed"] is True


def test_result_is_serialisable_for_the_decision_log():
    result = assess(make_conjunction(miss_m=100.0, sigma_m=50.0))
    payload = result.to_dict()

    import json

    text = json.dumps(payload)
    assert '"FOSTER_ESTES_2D"' in text
    assert json.loads(text)["inputs_hash"] == result.inputs_hash
