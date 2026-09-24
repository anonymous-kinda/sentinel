"""Shape the Compose stack's leaf link through the edge's own demo API.

    python -m harness.compose_link DENIED       (or: make compose-link PRESET=DENIED)

The edge accepts link presets only from its own loopback. That guard is the
application's (POST /api/demo/link in sentinel/api/app.py), and a request
from the host reaches a container from the Docker bridge, so it is refused
with 403 - including from the console's LINK chip in a browser. The request
is therefore made where an operator on the edge host would make it: inside
the edge's network namespace, with `docker compose exec`. The edge then
drives Toxiproxy exactly as in the process harness and `make demo-local`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from collections.abc import Callable

from sentinel.linkstate.toxiproxy import PRESETS
from sentinel.obs import configure_logging, get_logger

from .compose import COMPOSE_FILE

log = get_logger(__name__)

EDGE_SERVICE = "edge"
EDGE_DEMO_LINK = "http://127.0.0.1:8000/api/demo/link"   # the edge node, from inside its namespace
# Runs with the image's python; stdlib only, the preset is its one argument.
SNIPPET = (
    "import json, sys, urllib.request as u; "
    f"r = u.Request({EDGE_DEMO_LINK!r}, json.dumps({{'preset': sys.argv[1]}}).encode(), "
    "{'Content-Type': 'application/json'}, method='POST'); "
    "print(u.urlopen(r, timeout=10).read().decode())"
)


class LinkControlError(RuntimeError):
    """The edge (or Docker) refused to apply a preset."""


def link_command(preset: str, compose_file: pathlib.Path = COMPOSE_FILE) -> list[str]:
    return ["docker", "compose", "-f", str(compose_file), "exec", "-T", EDGE_SERVICE,
            "python", "-c", SNIPPET, preset]


def set_link(preset: str, compose_file: pathlib.Path = COMPOSE_FILE,
             run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict:
    """Apply a preset; the emulator's status as the edge reports it."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; one of {sorted(PRESETS)}")
    done = run(link_command(preset, compose_file), capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        log.error("Link preset not applied", preset=preset, returncode=done.returncode, stderr=done.stderr.strip()[-400:])
        raise LinkControlError(f"preset {preset} not applied (exit {done.returncode}): {done.stderr.strip()[-400:]}")
    log.info("Link preset applied", preset=preset)
    return json.loads(done.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shape the Compose stack's leaf link from inside the edge.")
    parser.add_argument("preset", choices=list(PRESETS))
    parser.add_argument("--compose-file", type=pathlib.Path, default=COMPOSE_FILE)
    args = parser.parse_args(argv)
    configure_logging()
    print(json.dumps(set_link(args.preset, compose_file=args.compose_file), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
