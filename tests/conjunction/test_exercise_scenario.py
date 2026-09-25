"""The exercise scenario does what sentinel/conjunction/exercise.py says it does.

The module's docstring is the roster a demonstrator reads to know what each
scripted event will show. Each claim is checked here by assessing the
event's CDMs with the engine and banding them with the default policy.
"""

import datetime as dt

import pytest

from sentinel.cdm.kvn import parse_bytes
from sentinel.cdm.to_conjunction import to_conjunction
from sentinel.conjunction.exercise import generate
from sentinel.conjunction.policy import Band, ConjunctionPolicy
from sentinel.risk.engine import assess
from sentinel.risk.types import AssessedConjunction

EPOCH = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.UTC)


def updates(key: str) -> list[tuple[dt.datetime, AssessedConjunction]]:
    """(TCA, assessment) for each of an event's CDMs, in release order."""
    found = []
    for item in generate(EPOCH):
        if item.filename.startswith(f"{key}-"):
            message = parse_bytes(item.kvn.encode())
            found.append((message.tca, assess(to_conjunction(message).conjunction)))
    return found


@pytest.fixture(scope="module")
def ex_red():
    return updates("EX-RED")


def test_ex_red_is_red_from_its_first_cdm(ex_red):
    policy = ConjunctionPolicy()
    assert len(ex_red) == 4
    assert [policy.band_for(result.pc) for _, result in ex_red] == [Band.RED] * 4


def test_ex_red_miss_closes_from_260_to_200_m(ex_red):
    misses = [result.miss_distance_m for _, result in ex_red]
    assert misses == sorted(misses, reverse=True)
    assert misses[0] == pytest.approx(260.0, abs=0.01) and misses[-1] == pytest.approx(200.0, abs=0.01)


def test_ex_red_pc_rises_while_diluted_and_eases_on_the_last_cdm_the_first_that_is_not(ex_red):
    pcs = [result.pc for _, result in ex_red]
    assert [result.dilution_flag for _, result in ex_red] == [True, True, True, False]
    assert pcs[:3] == sorted(pcs[:3])
    assert pcs[0] < pcs[-1] < pcs[2]


def test_ex_red_tca_is_19_hours_after_the_epoch(ex_red):
    assert {tca - EPOCH for tca, _ in ex_red} == {dt.timedelta(hours=19)}
