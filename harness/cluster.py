"""A two-node Sentinel deployment on one machine, with an emulated link.

    [edge node] -- nats(edge) --leaf--> toxiproxy --> nats(hub) -- [hub node]

Real processes, real TCP, real NATS leafnode protocol. Toxiproxy shapes the
one link that matters - the leaf connection - so every scenario exercises
the same code a deployed edge runs. No containers: nats-server and
toxiproxy are static binaries (deploy/tools.lock), so this runs the same in
WSL, on a laptop, and in GitHub Actions.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import platform
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / ".tools" / {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine(), platform.machine())


def allocate_ports(names: list[str]) -> dict[str, int]:
    """Distinct free ports: every socket stays bound until all are chosen,
    so the OS cannot hand the same port out twice."""
    sockets = []
    try:
        for _ in names:
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            sockets.append(s)
        return {name: s.getsockname()[1] for name, s in zip(names, sockets)}
    finally:
        for s in sockets:
            s.close()


def http(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: float = 10.0):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def wait_until(predicate, timeout: float, interval: float = 0.25, what: str = "condition"):
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        time.sleep(interval)
    raise TimeoutError(f"timed out after {timeout:.0f}s waiting for {what} (last error: {last_exc})")


class Cluster:
    def __init__(
        self,
        sync_mode: str = "edf",
        clock: str = "real",
        hub_exercise: bool = True,
        sync_interval_s: float = 1.0,
        keep: bool = False,
        web: bool = False,
        hub_port: int | None = None,
        edge_port: int | None = None,
    ):
        self.sync_mode = sync_mode
        self.clock = clock
        self.hub_exercise = hub_exercise
        self.sync_interval_s = sync_interval_s
        self.keep = keep
        self.web = web
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="sentinel-ddil-"))
        self.procs: dict[str, subprocess.Popen] = {}
        self.ports = allocate_ports([
            "hub_client", "hub_monitor", "hub_leaf", "hub_http",
            "edge_client", "edge_monitor", "edge_http",
            "toxi_api", "toxi_leaf",
        ])
        if hub_port:
            self.ports["hub_http"] = hub_port
        if edge_port:
            self.ports["edge_http"] = edge_port

    # ----------------------------------------------------------------- urls
    @property
    def hub(self) -> str:
        return f"http://127.0.0.1:{self.ports['hub_http']}"

    @property
    def edge(self) -> str:
        return f"http://127.0.0.1:{self.ports['edge_http']}"

    @property
    def toxi(self) -> str:
        return f"http://127.0.0.1:{self.ports['toxi_api']}"

    # --------------------------------------------------------------- start
    def _spawn(self, name: str, args: list[str], env: dict | None = None) -> None:
        log = open(self.dir / f"{name}.log", "wb")  # noqa: SIM115 - closed with the process
        self.procs[name] = subprocess.Popen(
            args, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **(env or {})}, cwd=ROOT
        )

    def _render(self, template: str, out: pathlib.Path, **values) -> None:
        text = string.Template((ROOT / "deploy" / "nats" / template).read_text()).substitute(values)
        out.write_text(text)

    def _identities(self) -> pathlib.Path:
        sys.path.insert(0, str(ROOT))
        from sentinel.crdt import NodeKey

        trust = {}
        for node in ("hub", "edge-alpha"):
            var = self.dir / node / "var"
            key = NodeKey.load_or_create(node, var / "keys" / f"{node}.ed25519.pem")
            trust[node] = key.public_hex()
        path = self.dir / "trust.json"
        path.write_text(json.dumps(trust, indent=1))
        return path

    def start(self) -> Cluster:
        for tool in ("nats-server", "toxiproxy"):
            if not (TOOLS / tool).exists():
                raise SystemExit(f"{TOOLS / tool} missing: run `make tools`")
        p = self.ports
        trust = self._identities()

        self._spawn("toxiproxy", [str(TOOLS / "toxiproxy"), "-host", "127.0.0.1", "-port", str(p["toxi_api"])])
        wait_until(lambda: http("GET", f"{self.toxi}/version") is not None or True, 10, what="toxiproxy")
        wait_until(lambda: http("POST", f"{self.toxi}/proxies", {
            "name": "leaf", "listen": f"127.0.0.1:{p['toxi_leaf']}",
            "upstream": f"127.0.0.1:{p['hub_leaf']}", "enabled": True,
        }), 10, what="toxiproxy proxy")

        (self.dir / "hub").mkdir(exist_ok=True)
        (self.dir / "edge-alpha").mkdir(exist_ok=True)
        self._render("hub.conf.tmpl", self.dir / "hub" / "nats.conf", NODE_ID="hub",
                     CLIENT_PORT=p["hub_client"], MONITOR_PORT=p["hub_monitor"],
                     LEAF_LISTEN=f"127.0.0.1:{p['hub_leaf']}", LEAF_TLS="")
        self._render("edge.conf.tmpl", self.dir / "edge-alpha" / "nats.conf", NODE_ID="edge-alpha",
                     CLIENT_PORT=p["edge_client"], MONITOR_PORT=p["edge_monitor"],
                     HUB_LEAF_URL=f"nats-leaf://127.0.0.1:{p['toxi_leaf']}", REMOTE_TLS="")
        self._spawn("nats-hub", [str(TOOLS / "nats-server"), "-c", str(self.dir / "hub" / "nats.conf")])
        self._spawn("nats-edge", [str(TOOLS / "nats-server"), "-c", str(self.dir / "edge-alpha" / "nats.conf")])

        common = {
            "SENTINEL_CLOCK": self.clock,
            "SENTINEL_TRUST_FILE": str(trust),
            "SENTINEL_LIBRARY": "1" if self.web else "0",
            "SENTINEL_WEB_DIST": str(ROOT / "web" / "dist") if self.web else "",
            "PYTHONUNBUFFERED": "1",
        }
        self._spawn("hub", [sys.executable, "-m", "sentinel.cli", "serve", "--port", str(p["hub_http"]), "--log-level", "warning"], {
            **common,
            "SENTINEL_NODE_ID": "hub", "SENTINEL_ROLE": "hub",
            "SENTINEL_NATS_URL": f"nats://127.0.0.1:{p['hub_client']}",
            "SENTINEL_DB": str(self.dir / "hub" / "sentinel.db"),
            "SENTINEL_VAR": str(self.dir / "hub" / "var"),
            "SENTINEL_EXERCISE": "1" if self.hub_exercise else "0",
        })
        self._spawn("edge", [sys.executable, "-m", "sentinel.cli", "serve", "--port", str(p["edge_http"]), "--log-level", "warning"], {
            **common,
            "SENTINEL_NODE_ID": "edge-alpha", "SENTINEL_ROLE": "edge", "SENTINEL_HUB_ID": "hub",
            "SENTINEL_NATS_URL": f"nats://127.0.0.1:{p['edge_client']}",
            "SENTINEL_DB": str(self.dir / "edge-alpha" / "sentinel.db"),
            "SENTINEL_VAR": str(self.dir / "edge-alpha" / "var"),
            "SENTINEL_EXERCISE": "0",
            "SENTINEL_SYNC_MODE": self.sync_mode,
            "SENTINEL_SYNC_INTERVAL_S": str(self.sync_interval_s),
            "SENTINEL_DEMO_CONTROLS": "1",
            "SENTINEL_TOXIPROXY_API": self.toxi,
        })
        wait_until(lambda: http("GET", f"{self.hub}/api/health"), 30, what="hub node")
        wait_until(lambda: http("GET", f"{self.edge}/api/health"), 30, what="edge node")
        return self

    # --------------------------------------------------------------- control
    def link(self, preset: str) -> dict:
        """Apply a link preset directly through Toxiproxy (the edge's demo API
        does the same; calling Toxiproxy keeps the harness independent of it)."""
        sys.path.insert(0, str(ROOT))
        from sentinel.linkstate.toxiproxy import ToxiproxyControl

        return ToxiproxyControl(self.toxi).apply(preset)

    def leaf_connected(self) -> bool:
        data = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.ports['edge_monitor']}/leafz", timeout=3).read())
        return bool(data.get("leafnodes"))

    def stop(self) -> None:
        for proc in self.procs.values():
            with contextlib.suppress(Exception):
                proc.terminate()
        for proc in self.procs.values():
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)
        for proc in self.procs.values():
            with contextlib.suppress(Exception):
                proc.kill()
        if not self.keep:
            shutil.rmtree(self.dir, ignore_errors=True)

    def logs(self, name: str, tail: int = 30) -> str:
        path = self.dir / f"{name}.log"
        return "\n".join(path.read_text(errors="replace").splitlines()[-tail:]) if path.exists() else ""

    def __enter__(self) -> Cluster:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
