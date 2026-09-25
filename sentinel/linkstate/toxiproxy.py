"""Link emulation for demonstrations and the DDIL harness (Toxiproxy).

Toxiproxy sits between the edge's nats-server and the hub's leafnode port
and shapes the *real* TCP connection: latency, bandwidth, disconnection.
The console exposes presets only when the node runs with
SENTINEL_DEMO_CONTROLS=1 and the request comes from localhost; the harness
drives the same API.

Note: the presets use Toxiproxy's latency, bandwidth and timeout toxics,
which shape a TCP stream. Packet loss below TCP, which TCP would
retransmit, is not emulated anywhere: there is no `tc netem`. The nightly
harness job runs the same presets and only lengthens the denial (900 s
rather than 20 s, .github/workflows/harness.yml).
"""

from __future__ import annotations

import json
import os
import urllib.request

PRESETS: dict[str, list[dict]] = {
    "CONNECTED": [],
    "DEGRADED": [
        {"name": "latency_down", "type": "latency", "stream": "downstream", "attributes": {"latency": 600, "jitter": 200}},
        {"name": "latency_up", "type": "latency", "stream": "upstream", "attributes": {"latency": 600, "jitter": 200}},
        {"name": "bw_down", "type": "bandwidth", "stream": "downstream", "attributes": {"rate": 32}},
        {"name": "bw_up", "type": "bandwidth", "stream": "upstream", "attributes": {"rate": 32}},
    ],
    # About 8 kbit/s each way: below a 9.6 kbit/s satellite channel.
    "LIMITED": [
        {"name": "latency_down", "type": "latency", "stream": "downstream", "attributes": {"latency": 600, "jitter": 100}},
        {"name": "latency_up", "type": "latency", "stream": "upstream", "attributes": {"latency": 600, "jitter": 100}},
        {"name": "bw_down", "type": "bandwidth", "stream": "downstream", "attributes": {"rate": 1}},
        {"name": "bw_up", "type": "bandwidth", "stream": "upstream", "attributes": {"rate": 1}},
    ],
    # A denied RF link is a black hole, not a polite TCP reset: data on the
    # live connection vanishes (timeout toxic with timeout 0) and no new
    # connection can be made (proxy disabled). NATS must detect it by ping.
    "DENIED": [
        {"name": "blackhole_down", "type": "timeout", "stream": "downstream", "attributes": {"timeout": 0}},
        {"name": "blackhole_up", "type": "timeout", "stream": "upstream", "attributes": {"timeout": 0}},
    ],
}


class ToxiproxyControl:
    def __init__(self, api: str | None = None, proxy: str = "leaf"):
        self.api = (api or os.environ.get("SENTINEL_TOXIPROXY_API", "http://127.0.0.1:8474")).rstrip("/")
        self.proxy = proxy
        self.preset = "CONNECTED"

    def _call(self, method: str, path: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"{self.api}{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def available(self) -> bool:
        try:
            self._call("GET", f"/proxies/{self.proxy}")
            return True
        except Exception:  # noqa: BLE001
            return False

    def apply(self, preset: str) -> dict:
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}; one of {sorted(PRESETS)}")
        proxy = self._call("GET", f"/proxies/{self.proxy}")
        for toxic in proxy.get("toxics", []):
            self._call("DELETE", f"/proxies/{self.proxy}/toxics/{toxic['name']}")
        for toxic in PRESETS[preset]:
            self._call("POST", f"/proxies/{self.proxy}/toxics", toxic)
        self._call("POST", f"/proxies/{self.proxy}", {"enabled": preset != "DENIED"})
        self.preset = preset
        return self.status()

    def status(self) -> dict:
        proxy = self._call("GET", f"/proxies/{self.proxy}")
        return {
            "preset": self.preset,
            "enabled": proxy.get("enabled"),
            "toxics": [{"name": t["name"], "type": t["type"], **t.get("attributes", {})} for t in proxy.get("toxics", [])],
        }
