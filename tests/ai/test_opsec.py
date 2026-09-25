"""A position typed into the assistant stays on the node (ADR-010).

With hosted AI on, the operator's question goes to Jev and to Claude. A
question that holds a position would carry it past all four of ADR-010's
layers, so the tier keeps such a question local. A false positive costs a
local answer; a false negative sends a position off the node. The rules
lean wide.
"""

import pytest

from sentinel.ai.opsec import holds_position

UNIT = (34.0522, -118.2437)           # the unit this node holds: lat, lon


@pytest.mark.parametrize(
    "question",
    [
        "can imagers see us at 34.0522, -118.2437?",
        "any pass over 34.05 tonight?",
        "we are at 118.24W",
        "is 34.1 inside a gap",
        "lat 34.052 lon -118.244",
    ],
)
def test_the_held_units_coordinates_at_any_precision_typed_are_a_position(question):
    assert holds_position(question, UNIT)


@pytest.mark.parametrize(
    "question",
    [
        "next gap at 11SLT8520012345?",
        "grid 11S LT 85200 12345",
        "unit at 18t wl 802 123",
        "34°03'08\"N 118°14'37\"W",
        "we moved to 38.90N 77.04W",
        "we moved to 38.90 N, 77.04 W",
        "38.8977, -77.0365",
        "38.8977 -77.0365",
    ],
)
def test_position_notation_is_a_position_whoever_it_belongs_to(question):
    """MGRS, degrees and hemisphere pairs keep a question local even when the
    node holds no unit, or the position is not the held unit's."""
    assert holds_position(question, None)
    assert holds_position(question, UNIT)


@pytest.mark.parametrize(
    "question",
    [
        "/events red 48h",
        "/assess 2",
        "/draft 118 maneuver",
        "what is the risk on EX-DEB 118",
        "is the DEB 412 event diluted?",
        "which events need action in the next 24 hours",
        "anything due within 10.9 h?",
        "Pc 6.3e-3 on 99118, is that red?",
        "draft a no maneuver decision for 207",
        "how is the link to the hub doing",
        "/explain 99001-99118-20260924T205723",
        "why is it 34 hours to TCA",
    ],
)
def test_ordinary_questions_are_not_positions(question):
    assert not holds_position(question, UNIT)
    assert not holds_position(question, None)


def test_a_whole_number_alone_never_matches_the_unit():
    """Integers are hours, counts and catalog numbers far more often than a
    one-degree position; a hemisphere letter or degree sign still catches one."""
    unit = (48.0, 11.0)
    assert not holds_position("/events red 48h", unit)
    assert not holds_position("what is due in 11 hours", unit)
    assert holds_position("we are at 48N 11E", unit)
