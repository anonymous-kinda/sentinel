"""Which AI tier may run, decided from measured link state and marking.

    System One (routing):  Jev (hosted)           | deterministic router
    System Two (prose):    Claude (hosted)         | deterministic templates
    Numbers:               always deterministic code

Hosted AI needs an UNCLASSIFIED marking and explicit opt-in. Jev may run on
a LIMITED link - its answer is a few probabilities, not prose - but a
hosted LLM may not. DENIED means local only. Nothing here is a flag an
operator forgets to reset: link state is measured.
"""

import pytest

from sentinel.ai.policy import TierInputs, decide

UNCLASS = "UNCLASSIFIED // EXERCISE"


def inputs(**overrides):
    base = dict(link_state="CONNECTED", marking=UNCLASS, jev_configured=True, claude_configured=True, cloud_opt_in=True)
    return TierInputs(**{**base, **overrides})


@pytest.mark.parametrize(
    "overrides,router,narrator",
    [
        ({}, "jev", "claude"),
        ({"link_state": "DEGRADED"}, "jev", "claude"),
        ({"link_state": "LIMITED"}, "jev", "template"),
        ({"link_state": "DENIED"}, "deterministic", "template"),
        ({"link_state": "UNKNOWN"}, "deterministic", "template"),
        ({"marking": "SECRET // NOFORN"}, "deterministic", "template"),
        ({"cloud_opt_in": False}, "deterministic", "template"),
        ({"jev_configured": False}, "deterministic", "claude"),
        ({"claude_configured": False}, "jev", "template"),
    ],
)
def test_tier_table(overrides, router, narrator):
    decision = decide(inputs(**overrides))
    assert (decision.router, decision.narrator) == (router, narrator)
    assert decision.reason


def test_reasons_name_the_constraint():
    assert "LIMITED" in decide(inputs(link_state="LIMITED")).reason
    assert "classified" in decide(inputs(marking="SECRET")).reason.lower()
    assert "DENIED" in decide(inputs(link_state="DENIED")).reason
