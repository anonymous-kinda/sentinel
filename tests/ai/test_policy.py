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
    assert "marking" in decide(inputs(marking="SECRET")).reason.lower()
    assert "DENIED" in decide(inputs(link_state="DENIED")).reason


def test_a_question_that_holds_a_position_stays_on_the_node():
    """ADR-010: a unit's position never leaves its edge, and a hosted service
    would receive the question's text."""
    decision = decide(inputs(question_holds_position=True))
    assert (decision.router, decision.narrator) == ("deterministic", "template")
    assert "position" in decision.reason and "ADR-010" in decision.reason
    assert decide(inputs()).router == "jev", "the same node routes hosted when the question holds none"


# ---------------------------------------------------------------- marking
@pytest.mark.parametrize(
    "marking",
    ["UNCLASSIFIED", "UNCLASSIFIED // EXERCISE", "UNCLASSIFIED//EXERCISE", "unclassified  //  exercise"],
)
def test_hosted_ai_is_allowed_under_an_allow_listed_marking(marking):
    """Case and the spacing around // are how a banner is typed, not what it says."""
    assert (decide(inputs(marking=marking)).router, decide(inputs(marking=marking)).narrator) == ("jev", "claude")


@pytest.mark.parametrize(
    "marking",
    [
        "UNCLASSIFIED//CUI",
        "UNCLASSIFIED // FOUO",
        "UNCLASSIFIED//FOR OFFICIAL USE ONLY",
        "UNCLASSIFIED//NOFORN",
        "UNCLASSIFIED // EXERCISE // CUI",
        "UNCLASSIFIED//PROPIN",
        "UNCLASSIFIED//",
        "UNCLASSIFIED-ISH",
        "CUI",
        "SECRET",
        "MARKING UNKNOWN",
        "",
    ],
)
def test_a_caveated_or_unknown_marking_keeps_ai_on_the_node(marking):
    """Starting with UNCLASSIFIED is not enough: a dissemination caveat limits
    who may receive the text, and a hosted service is a recipient no caveat
    names. Only an exact allow-listed marking lets text leave the node."""
    decision = decide(inputs(marking=marking))
    assert (decision.router, decision.narrator) == ("deterministic", "template")
    assert "UNCLASSIFIED // EXERCISE" in decision.reason and "caveat" in decision.reason
