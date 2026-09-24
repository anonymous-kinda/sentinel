"""Node settings, from environment variables (12-factor; systemd-friendly)."""

from __future__ import annotations

import dataclasses
import os
import pathlib


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclasses.dataclass(frozen=True)
class Settings:
    node_id: str = "standalone"
    role: str = "standalone"                 # hub | edge | standalone
    db_path: str = ":memory:"
    marking: str = "UNCLASSIFIED // EXERCISE"
    exercise: bool = True                    # run the scripted exercise scenario
    library: bool = True                     # load NASA CARA reference events
    read_only: bool = False                  # public node: no ingest, no writes
    demo_controls: bool = False              # link-emulation controls (localhost only)
    web_dist: str | None = None              # built web UI to serve at /
    nats_url: str | None = None              # this node's own nats-server; None = in-process bus
    hub_id: str | None = None                # edges: the hub to sync from
    sync_mode: str = "edf"                   # edf | fifo (fifo = measured baseline only)
    sync_interval_s: float = 2.0
    var_dir: str = "var"                     # node keys and state
    trust_file: str | None = None            # node_id -> Ed25519 public key (JSON)
    toxiproxy_api: str | None = None         # demo/harness link emulation

    @classmethod
    def from_env(cls) -> Settings:
        default_web = pathlib.Path(__file__).resolve().parents[2] / "web" / "dist"
        return cls(
            node_id=os.environ.get("SENTINEL_NODE_ID", "standalone"),
            role=os.environ.get("SENTINEL_ROLE", "standalone"),
            db_path=os.environ.get("SENTINEL_DB", ":memory:"),
            marking=os.environ.get("SENTINEL_MARKING", "UNCLASSIFIED // EXERCISE"),
            exercise=_flag("SENTINEL_EXERCISE", True),
            library=_flag("SENTINEL_LIBRARY", True),
            read_only=_flag("SENTINEL_READ_ONLY", False),
            demo_controls=_flag("SENTINEL_DEMO_CONTROLS", False),
            web_dist=os.environ.get("SENTINEL_WEB_DIST")
            or (str(default_web) if default_web.exists() else None),
            nats_url=os.environ.get("SENTINEL_NATS_URL") or None,
            hub_id=os.environ.get("SENTINEL_HUB_ID") or None,
            sync_mode=os.environ.get("SENTINEL_SYNC_MODE", "edf"),
            sync_interval_s=float(os.environ.get("SENTINEL_SYNC_INTERVAL_S", "2.0")),
            var_dir=os.environ.get("SENTINEL_VAR", "var"),
            trust_file=os.environ.get("SENTINEL_TRUST_FILE") or None,
            toxiproxy_api=os.environ.get("SENTINEL_TOXIPROXY_API") or None,
        )
