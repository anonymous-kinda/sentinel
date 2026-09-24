#!/usr/bin/env python3
"""Render the Compose stack's NATS and Toxiproxy configs into deploy/compose/.

    uv run python scripts/compose_config.py        (or: make compose-config)

They come from deploy/nats/*.tmpl through the process harness's own
rendering (harness/cluster.py), so the leaf permissions and the DDIL fixes
cannot drift from what every DDIL scenario runs. The files are committed,
so `docker compose up` needs nothing but Docker; tests/test_compose_config.py
fails if they no longer match this script's output.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from harness.compose import COMPOSE_DIR, write_configs  # noqa: E402
from sentinel.obs import configure_logging, get_logger  # noqa: E402

log = get_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=pathlib.Path, default=COMPOSE_DIR)
    args = parser.parse_args()
    configure_logging()
    for path in write_configs(args.out):
        log.info("Compose config written", path=str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
