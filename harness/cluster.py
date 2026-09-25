"""A two-node Sentinel deployment on one machine, with an emulated link.

    [edge node] -- nats(edge) --leaf--> toxiproxy --> nats(hub) -- [hub node]

Real processes, real TCP, real NATS leafnode protocol. Toxiproxy shapes the
one link that matters - the leaf connection - so every scenario exercises
the same code a deployed edge runs. No containers: nats-server and
toxiproxy are static binaries (deploy/tools.lock), so this runs the same in
WSL, on a laptop, and in GitHub Actions. The Compose stack (deploy/compose,
harness/compose.py) runs the same topology in containers, from the same
config rendering below.
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
NATS_TEMPLATES = ROOT / "deploy" / "nats"
HUB_ID = "hub"
EDGE_ID = "edge-alpha"
LEAF_PROXY = "leaf"  # the Toxiproxy proxy name sentinel.linkstate.toxiproxy shapes


# ------------------------------------------------------------------ configs
# One rendering for every two-node deployment: this harness and the Compose
# stack (harness/compose.py) differ only in the addresses they pass in.
def render_nats(template: str, **values) -> str:
    return string.Template((NATS_TEMPLATES / template).read_text()).substitute(values)


def hub_nats_conf(client_port: int, monitor_port: int, leaf_listen: str) -> str:
    """The hub's nats-server: its own bus, plus the listener leaves dial."""
    return render_nats("hub.conf.tmpl", NODE_ID=HUB_ID, CLIENT_PORT=client_port, MONITOR_PORT=monitor_port,
                       LEAF_LISTEN=leaf_listen, LEAF_TLS="")


def edge_nats_conf(client_port: int, monitor_port: int, hub_leaf_url: str) -> str:
    """The edge's nats-server: its own bus, plus one leaf link to the hub."""
    return render_nats("edge.conf.tmpl", NODE_ID=EDGE_ID, CLIENT_PORT=client_port, MONITOR_PORT=monitor_port,
                       HUB_LEAF_URL=hub_leaf_url, REMOTE_TLS="")


def leaf_proxy(listen: str, upstream: str) -> dict:
    """The one Toxiproxy proxy: the edge's leaf connection, on its way to the hub."""
    return {"name": LEAF_PROXY, "listen": listen, "upstream": upstream, "enabled": True}


def toxic_spec(toxic: dict) -> dict:
    """One toxic in a comparable form, whether a preset states it or Toxiproxy reports it."""
    return {
        "name": toxic["name"],
        "type": toxic["type"],
        "stream": toxic["stream"],
        "toxicity": float(toxic.get("toxicity", 1.0)),
        "attributes": toxic.get("attributes", {}),
    }


def preset_toxics(preset: str) -> list[dict]:
    """The toxics a link preset puts on the leaf connection."""
    sys.path.insert(0, str(ROOT))
    from sentinel.linkstate.toxiproxy import PRESETS

    return [toxic_spec(toxic) for toxic in PRESETS[preset]]


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
        hub_elements: bool = True,
        initial_link: str = "CONNECTED",
    ):
        """`initial_link` is the preset on the leaf connection before either
        nats-server starts: DENIED keeps the edge from syncing anything until
        the caller shapes the link, so the first byte crosses a known link."""
        self.sync_mode = sync_mode
        self.hub_elements = hub_elements
        self.initial_link = initial_link
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

    def write_nats_configs(self) -> None:
        p = self.ports
        configs = {
            HUB_ID: hub_nats_conf(p["hub_client"], p["hub_monitor"], f"127.0.0.1:{p['hub_leaf']}"),
            EDGE_ID: edge_nats_conf(p["edge_client"], p["edge_monitor"], f"nats-leaf://127.0.0.1:{p['toxi_leaf']}"),
        }
        for node, text in configs.items():
            (self.dir / node).mkdir(exist_ok=True)
            (self.dir / node / "nats.conf").write_text(text)

    def _identities(self) -> pathlib.Path:
        sys.path.insert(0, str(ROOT))
        from .identity import enroll

        path = self.dir / "trust.json"
        for node in (HUB_ID, EDGE_ID):
            enroll(node, self.dir / node / "var", path)
        return path

    def elements_env(self) -> dict[str, dict[str, str]]:
        """SENTINEL_ELEMENTS per node. Empty means the node's role default:
        the hub loads the vendored snapshot, and the edge loads none and
        syncs element sets from the hub - whatever the calling shell sets.
        A conjunction-only hub starts from an empty snapshot."""
        hub = ""
        if not self.hub_elements:
            empty = self.dir / "no-elements.json"
            empty.write_text("[]")
            hub = str(empty)
        return {"hub": {"SENTINEL_ELEMENTS": hub}, "edge": {"SENTINEL_ELEMENTS": ""}}

    def start(self) -> Cluster:
        for tool in ("nats-server", "toxiproxy"):
            if not (TOOLS / tool).exists():
                raise SystemExit(f"{TOOLS / tool} missing: run `make tools`")
        p = self.ports
        trust = self._identities()
        elements = self.elements_env()

        self._spawn("toxiproxy", [str(TOOLS / "toxiproxy"), "-host", "127.0.0.1", "-port", str(p["toxi_api"])])
        wait_until(lambda: http("GET", f"{self.toxi}/version") is not None or True, 10, what="toxiproxy")
        wait_until(lambda: http("POST", f"{self.toxi}/proxies",
                                leaf_proxy(f"127.0.0.1:{p['toxi_leaf']}", f"127.0.0.1:{p['hub_leaf']}")),
                   10, what="toxiproxy proxy")
        self.link(self.initial_link)

        self.write_nats_configs()
        self._spawn("nats-hub", [str(TOOLS / "nats-server"), "-c", str(self.dir / HUB_ID / "nats.conf")])
        self._spawn("nats-edge", [str(TOOLS / "nats-server"), "-c", str(self.dir / EDGE_ID / "nats.conf")])

        common = {
            "SENTINEL_CLOCK": self.clock,
            "SENTINEL_TRUST_FILE": str(trust),
            "SENTINEL_LIBRARY": "1" if self.web else "0",
            "SENTINEL_WEB_DIST": str(ROOT / "web" / "dist") if self.web else "",
            "PYTHONUNBUFFERED": "1",
        }
        self._spawn("hub", [sys.executable, "-m", "sentinel.cli", "serve", "--port", str(p["hub_http"]), "--log-level", "warning"], {
            **common,
            **elements["hub"],
            "SENTINEL_NODE_ID": HUB_ID, "SENTINEL_ROLE": "hub",
            "SENTINEL_NATS_URL": f"nats://127.0.0.1:{p['hub_client']}",
            "SENTINEL_DB": str(self.dir / HUB_ID / "sentinel.db"),
            "SENTINEL_VAR": str(self.dir / HUB_ID / "var"),
            "SENTINEL_EXERCISE": "1" if self.hub_exercise else "0",
        })
        self._spawn("edge", [sys.executable, "-m", "sentinel.cli", "serve", "--port", str(p["edge_http"]), "--log-level", "warning"], {
            **common,
            **elements["edge"],
            "SENTINEL_NODE_ID": EDGE_ID, "SENTINEL_ROLE": "edge", "SENTINEL_HUB_ID": HUB_ID,
            "SENTINEL_NATS_URL": f"nats://127.0.0.1:{p['edge_client']}",
            "SENTINEL_DB": str(self.dir / EDGE_ID / "sentinel.db"),
            "SENTINEL_VAR": str(self.dir / EDGE_ID / "var"),
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

    def toxics(self) -> list[dict]:
        """The toxics on the leaf connection now, as Toxiproxy reports them."""
        return [toxic_spec(toxic) for toxic in http("GET", f"{self.toxi}/proxies/{LEAF_PROXY}")["toxics"]]

    def leafz(self, side: str = "edge") -> dict:
        """The leaf connection as one side's nats-server reports it (`hub` or `edge`)."""
        url = f"http://127.0.0.1:{self.ports[f'{side}_monitor']}/leafz"
        return json.loads(urllib.request.urlopen(url, timeout=3).read())

    def leaf_connected(self) -> bool:
        return bool(self.leafz().get("leafnodes"))

    def leaf_compression(self) -> dict[str, str | None]:
        """What each side compresses the leaf's traffic with. s2_auto picks
        the level from a round trip that side measured, so on one link the
        two sides can differ, and a level chosen before shaping can persist."""
        levels = {}
        for side in ("hub", "edge"):
            leafs = self.leafz(side).get("leafs") or []
            levels[side] = leafs[0].get("compression") if leafs else None
        return levels

    def link_now(self) -> dict:
        """The link as the harness can check it: Toxiproxy's toxics and the leaf's compression."""
        return {"toxics": self.toxics(), "compression": self.leaf_compression()}

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
