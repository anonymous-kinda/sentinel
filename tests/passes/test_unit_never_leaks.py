"""The unit's position never reaches a log line, a bus message or an error.

One distinctive position is put through every path the pass module has:
set, read back, used, rejected, replaced, found corrupt on restart and
deleted. Every log record at DEBUG, with its structured fields, and every
bus message is then searched for it.
"""

import datetime as dt
import logging
import pathlib

from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.settings import Settings
from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock

SNAPSHOT = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "omm" / "celestrak-resource-20260924.json"
NOW = dt.datetime(2026, 9, 24, 6, 0, 30, tzinfo=dt.UTC)
LAT, LON = "35.123457", "-116.987653"
UNIT = {"unit_id": "EX-UNIT-1", "lat_deg": float(LAT), "lon_deg": float(LON), "alt_m": 712.5, "reaction_time_min": 30.0}


class RecordingBus(InProcessBus):
    def __init__(self):
        super().__init__()
        self.seen: list[bytes] = []

    async def publish(self, subject, data, headers=None):
        self.seen.append(subject.encode() + data + repr(headers).encode())
        await super().publish(subject, data, headers)


def node(tmp_path, bus):
    settings = Settings(exercise=False, library=False, web_dist=None, var_dir=str(tmp_path), elements_path=str(SNAPSHOT))
    return TestClient(create_app(settings, clock=FixedClock(NOW), bus=bus, start_background=False),
                      raise_server_exceptions=False)


def test_the_position_is_in_no_log_record_bus_message_or_error(tmp_path, caplog):
    bus = RecordingBus()
    caplog.set_level(logging.DEBUG)
    errors = []
    with node(tmp_path, bus) as client:
        assert client.put("/api/passes/unit", json=UNIT).status_code == 200
        assert client.get("/api/passes?hours=6").status_code == 200
        for wrong in ({"lat_deg": 91.123457}, {"lon_deg": 181.987653}, {"alt_m": 1e9}, {"reaction_time_min": -1},
                      {"lat_deg": LAT}):
            r = client.put("/api/passes/unit", json={**UNIT, **wrong})
            assert r.status_code == 422
            errors.append(r.text)
        errors.append(client.put("/api/passes/unit", content=b'{"lat_deg": 35.123457,').text)
    (tmp_path / "unit.json").write_text('{"unit_id": "EX", "lat_deg": 35.123457, "lon_deg": 999}')
    with node(tmp_path, bus) as client:                          # restart: the stored unit is refused
        assert client.get("/api/passes/unit").status_code == 404
        assert client.delete("/api/passes/unit").status_code == 204

    searched = {
        "log": "\n".join(f"{r.getMessage()} {getattr(r, 'fields', '')} {r.exc_text or ''}" for r in caplog.records),
        "bus": b"\n".join(bus.seen).decode("utf-8", "replace"),
        "errors": "\n".join(errors),
    }
    for where, text in searched.items():
        for secret in (LAT, LON.lstrip("-"), "91.123457", "181.987653"):
            assert secret not in text, f"{secret} reached the {where}"
    assert caplog.records, "the search covered real log output"
