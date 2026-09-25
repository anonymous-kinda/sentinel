"""The exercise scenario is the same scenario whatever timezone its epoch is
written in: every time in a message, its MESSAGE_ID and its file name are UTC.

An epoch of 14:00+02:00 used to write TCA and CREATION_DATE in UTC but the
MESSAGE_ID (and so the file name) at 14:00, two hours from the body it names.
"""

import datetime as dt

import pytest

from sentinel.cdm import parse
from sentinel.conjunction.exercise import generate

EPOCH = dt.datetime(2026, 9, 24, 12, tzinfo=dt.UTC)
PLUS_TWO = EPOCH.astimezone(dt.timezone(dt.timedelta(hours=2)))


def test_an_epoch_with_an_offset_generates_the_scenario_it_generates_in_utc():
    assert [(s.filename, s.kvn) for s in generate(PLUS_TWO)] == [(s.filename, s.kvn) for s in generate(EPOCH)]


def test_each_message_id_carries_its_own_creation_date():
    for item in generate(PLUS_TWO):
        message = parse(item.kvn)
        assert message.message_id.endswith(f"-{message.creation_date:%Y%m%dT%H%M%S}")
        assert item.filename == f"{message.message_id}.cdm"


def test_a_naive_epoch_is_refused_not_read_as_local_time():
    with pytest.raises(ValueError, match="naive"):
        generate(EPOCH.replace(tzinfo=None))
