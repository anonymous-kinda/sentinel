"""Hostile KVN at the ingest seam: nothing raises, nothing poisons the store.

Ingest either admits a CDM or quarantines it with a named reason. What it
admits, every view must then be able to show: a CDM stored and then found
unshowable breaks the event list for every CDM on the node, and on a hub
it breaks the manifest every edge syncs from.
"""

import asyncio
import contextlib
import datetime as dt
import json
import signal

import pytest
from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.settings import Settings
from sentinel.bus import InProcessBus
from sentinel.cdm import CdmRejected, parse, to_conjunction
from sentinel.cdm.validate import (
    EARTH_HILL_SPHERE_KM,
    MAX_POSITION_VARIANCE_M2,
    MAX_SPEED_KM_S,
    WGS84_POLAR_RADIUS_KM,
)
from sentinel.clock import FixedClock
from sentinel.conjunction.service import ConjunctionService
from sentinel.conjunction.store import ConjunctionStore
from sentinel.conjunction.trajectory import TrajectoryUnavailable

from .test_cdm_codec import OPERATIONAL, _replace

# numpy answers an overflow with a warning and an inf, then carries on. A
# hostile CDM must be judged before its numbers can overflow, not after.
pytestmark = pytest.mark.filterwarnings("error::RuntimeWarning")

NOW = dt.datetime(2026, 9, 23, 12, tzinfo=dt.UTC)
BASE = OPERATIONAL.read_text()
VIEW_BUDGET_S = 10


def _drop(text: str, key: str) -> str:
    return "\n".join(line for line in text.splitlines() if line.split("=")[0].strip() != key) + "\n"


def _mutate(key: str, value: str, occurrence: int = 1, text: str = BASE) -> str:
    unit = {"X": " [km]", "Y": " [km]", "Z": " [km]", "X_DOT": " [km/s]", "CR_R": " [m**2]"}.get(key, "")
    return _replace(text, key, f"{key} = {value}{unit}", occurrence)


# Without the header miss distance, only the state checks stand between an
# absurd state and the engine.
NO_HEADER_MISS = _drop(BASE, "MISS_DISTANCE")


def _state(position_km: tuple[float, float, float], velocity_km_s: tuple[float, float, float]) -> str:
    text = NO_HEADER_MISS
    for key, value in zip(("X", "Y", "Z", "X_DOT", "Y_DOT", "Z_DOT"), (*position_km, *velocity_km_s)):
        text = _mutate(key, repr(value), text=text)
    return text


POSITION_COVARIANCE = ("CR_R", "CT_R", "CT_T", "CN_R", "CN_T", "CN_N")


def _scaled_covariance(factor: float, text: str = BASE) -> str:
    """Both objects' position covariances times `factor`, units kept."""
    lines = []
    for line in text.splitlines():
        key, _, rest = line.partition("=")
        if key.strip() in POSITION_COVARIANCE:
            value, _, unit = rest.strip().partition(" ")
            line = f"{key.strip()} = {float(value) * factor!r} {unit}".rstrip()
        lines.append(line)
    return "\n".join(lines) + "\n"


HOSTILE = {
    # Admitted, and refused by the engine (UNRESOLVED_INTEGRAL): a sigma so
    # far below the hard-body radius that the integral cannot be resolved.
    "covariance-too-small-to-integrate": _scaled_covariance(1e-36),
    "originator-pc-not-a-number": _mutate("COLLISION_PROBABILITY", "abc"),
    "originator-pc-nan": _mutate("COLLISION_PROBABILITY", "NaN"),
    "originator-pc-infinite": _mutate("COLLISION_PROBABILITY", "inf"),
    "tca-in-year-1": _mutate("TCA", "0001-01-01T00:00:00.000"),
    "tca-day-of-year-past-9999": _mutate("TCA", "9999-366T00:00:00"),
    "creation-day-of-year-past-9999": _mutate("CREATION_DATE", "9999-366T00:00:00"),
    "tca-at-the-end-of-9999": _mutate("TCA", "9999-12-31T23:59:59.999"),
    "position-1e305-km": _mutate("X", "1e305", text=NO_HEADER_MISS),
    "position-1e305-km-with-header-miss": _mutate("X", "1e305"),
    "position-at-earth-centre": _mutate("Z", "0.001", text=_mutate("Y", "0.001", text=_mutate("X", "0.001", text=NO_HEADER_MISS))),
    "position-past-the-float-limit": _state((1.7e308, 1.7e308, 0.0), (7.5, 0.0, 0.0)),
    "velocity-1e305-km-s": _mutate("X_DOT", "1e305", text=NO_HEADER_MISS),
    "covariance-1e308": _mutate("CR_R", "1e308"),
    "covariance-minus-1e308": _mutate("CR_R", "-1e308"),
    "falling-through-the-earth": _mutate("Z_DOT", "-1000", text=_mutate("Y_DOT", "0", text=_mutate("X_DOT", "0", text=NO_HEADER_MISS))),
    # A plausible state (a straight fall from 7,000 km) whose arc still meets the Earth's centre.
    "radial-through-the-centre": _state((0.0, 0.0, 7000.0), (0.0, 0.0, -7.5)),
}


class ViewTooSlow(Exception):
    pass


@contextlib.contextmanager
def time_limit(seconds: int):
    """A view that never returns must fail the test, not hang the suite."""

    def expire(_signum, _frame):
        raise ViewTooSlow(f"no answer within {seconds} s")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _service() -> ConjunctionService:
    return ConjunctionService(ConjunctionStore(":memory:"), InProcessBus(), FixedClock(NOW))


def _ingest(service: ConjunctionService, text: str):
    return asyncio.run(service.ingest(text.encode(), "hostile", "REAL"))


def _served(view) -> None:
    """The API serialises with allow_nan=False: a NaN or an infinity in a
    view is a 500, not a number."""
    json.dumps(view, allow_nan=False, default=str)


def _show_everything(service: ConjunctionService) -> None:
    for scope in ("active", "past", "all"):
        _served(service.list_events(scope))
    _served(service.manifest())
    for event in service.store.events():
        _served(service.event_detail(event.event_id))
        _served(service.encounter(event.event_id))
        _served(service.dilution_curve(event.event_id))
        with contextlib.suppress(TrajectoryUnavailable):
            _served(service.trajectory(event.event_id))
        _served(service.current_ref(event.event_id))


@pytest.mark.parametrize("text", HOSTILE.values(), ids=HOSTILE.keys())
def test_hostile_kvn_is_admitted_or_quarantined_and_never_poisons_a_view(text):
    service = _service()
    result = _ingest(service, text)
    assert result.status in {"accepted", "rejected"}
    if result.status == "rejected":
        assert service.quarantined()[-1]["code"] == result.code
    with time_limit(VIEW_BUDGET_S):
        _show_everything(service)


def test_one_poisoned_cdm_leaves_the_rest_of_the_node_working():
    service = _service()
    good = _ingest(service, (OPERATIONAL.parent / "000020580_conj_000022015_20210315_212955_20210313_065123.cdm").read_text())
    _ingest(service, HOSTILE["originator-pc-not-a-number"])
    assert [e["event_id"] for e in service.list_events("all")] == [good.event_id]


@pytest.mark.parametrize("key,value,code", [
    ("COLLISION_PROBABILITY", "abc", "UNREADABLE"),
    ("COLLISION_PROBABILITY", "NaN", "UNREADABLE"),
    ("COLLISION_PROBABILITY", "-inf", "UNREADABLE"),
    ("MISS_DISTANCE", "abc", "UNREADABLE"),
    ("X", "1e306", "IMPLAUSIBLE_STATE"),      # finite in km, infinite in metres: judged before conversion
    ("TCA", "0001-01-01T00:00:00.000", "BAD_TCA"),
    ("TCA", "1957-10-03T23:59:59.999", "BAD_TCA"),
    ("TCA", "9999-366T00:00:00", "BAD_TCA"),
    ("CREATION_DATE", "9999-366T00:00:00", "BAD_CREATION_DATE"),
    ("CREATION_DATE", "1957-10-03T23:59:59.999", "BAD_CREATION_DATE"),
])
def test_unreadable_or_impossible_header_values_are_quarantined_with_a_reason(key, value, code):
    service = _service()
    result = _ingest(service, _mutate(key, value))
    assert (result.status, result.code) == ("rejected", code)


@pytest.mark.parametrize("key,value", [
    ("X", "1e100"),          # beyond Earth's sphere of influence: finite, but not an Earth orbit
    ("X", "1.6e6"),          # just beyond Earth's Hill sphere (~1.5 million km)
    ("X", "0.001"),          # with Y, Z below: at the Earth's centre
    ("X_DOT", "1e6"),        # faster than light, and the engine still computes a Pc
    ("CR_R", "1e308"),       # a variance no position estimate can have
])
def test_a_state_no_earth_orbiting_object_can_have_is_quarantined(key, value):
    text = _mutate(key, value, text=NO_HEADER_MISS)
    if key == "X" and value == "0.001":
        text = _mutate("Z", "0.001", text=_mutate("Y", "0.001", text=text))
    with pytest.raises(CdmRejected) as excinfo:
        to_conjunction(parse(text))
    assert excinfo.value.code == "IMPLAUSIBLE_STATE"


@pytest.mark.parametrize("text", [
    _state((WGS84_POLAR_RADIUS_KM, 0.0, 0.0), (0.0, 7.9, 0.0)),
    _state((EARTH_HILL_SPHERE_KM, 0.0, 0.0), (0.0, 0.5, 0.0)),
    _state((7000.0, 0.0, 0.0), (0.0, MAX_SPEED_KM_S, 0.0)),
    _mutate("CR_R", repr(MAX_POSITION_VARIANCE_M2)),
], ids=["on-the-surface", "at-the-hill-sphere", "at-the-speed-bound", "at-the-variance-bound"])
def test_the_physical_bounds_themselves_are_admitted(text):
    to_conjunction(parse(text))


def test_a_position_in_metres_under_a_km_label_is_quarantined():
    """No Earth orbit is closer than 6,357 km: in metres, that reads as 6.4 million km."""
    primary = parse(BASE).objects[0]
    position_m = tuple(1000.0 * primary.number(key) for key in ("X", "Y", "Z"))
    velocity_km_s = tuple(primary.number(key) for key in ("X_DOT", "Y_DOT", "Z_DOT"))
    with pytest.raises(CdmRejected) as excinfo:
        to_conjunction(parse(_state(position_m, velocity_km_s)))
    assert excinfo.value.code == "IMPLAUSIBLE_STATE"


@pytest.mark.parametrize("key,repeat", [
    ("X", "X = 31.5 [km]"),                        # within an object block
    ("TCA", "TCA = 2021-03-26T00:00:00.000"),      # within the header and relative metadata
])
def test_a_repeated_keyword_is_ambiguous_and_quarantined(key, repeat):
    """Two values for one keyword: which one the sender meant is a guess,
    and a reader that takes the last would compute a different answer."""
    lines = BASE.splitlines()
    first = next(i for i, line in enumerate(lines) if line.split("=")[0].strip() == key)
    lines.insert(first + 1, repeat)
    service = _service()
    result = _ingest(service, "\n".join(lines) + "\n")
    assert (result.status, result.code) == ("rejected", "PARSE_ERROR")
    assert f"{key} appears twice" in result.detail


def test_an_event_whose_arcs_cannot_be_drawn_answers_422_not_500(tmp_path):
    settings = Settings(exercise=False, library=False, web_dist=None, var_dir=str(tmp_path))
    with TestClient(create_app(settings, clock=FixedClock(NOW)), raise_server_exceptions=False) as client:
        accepted = client.post("/api/ingest/cdm", content=HOSTILE["radial-through-the-centre"].encode())
        assert accepted.status_code == 201, accepted.text
        r = client.get(f"/api/events/{accepted.json()['event_id']}/trajectory")
    assert r.status_code == 422
    assert r.json()["detail"] == "the two-body arcs cannot be drawn for this event"


def test_a_covariance_too_small_to_integrate_is_refused_by_name_and_draws_no_curve():
    service = _service()
    _ingest(service, HOSTILE["covariance-too-small-to-integrate"])
    [event] = service.list_events("all")
    assert event["assessment"]["refusal_reason"] == "UNRESOLVED_INTEGRAL"
    assert service.dilution_curve(event["event_id"]) is None
