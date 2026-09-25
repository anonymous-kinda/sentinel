"""Run a hub and an edge locally, each with its own console, for a live demo.

    make demo-local          # hub http://127.0.0.1:8000, edge http://127.0.0.1:8001

Open both side by side. On the edge, the LINK chip in the top bar measures
the real leafnode connection; its presets shape that connection through
Toxiproxy. Suggested sequence (docs/demo-script.md):

  1. CONNECTED - both consoles agree; every edge event is VERIFIED.
  2. DENIED    - edge keeps working: triage an event, record a decision.
                 On the hub, set a different triage status on the same event.
  3. LIMITED   - watch the Sync tab: summaries first, then the most urgent
                 record; triage status arrives as a CONFLICT on both sides.
  4. CONNECTED - everything converges; the offline decision is flagged
                 REVIEW REQUIRED if its CDM was superseded meanwhile.
"""

from __future__ import annotations

import signal
import sys
import time

from sentinel import localenv

from .cluster import Cluster, http, wait_until


def main() -> int:
    cluster = Cluster(hub_exercise=True, web=True, hub_port=8000, edge_port=8001, sync_interval_s=1.0)
    cluster.start()
    wait_until(cluster.leaf_connected, 20, what="leaf connection")
    print(f"""
  Sentinel demo is up (state in {cluster.dir})

    HUB   {cluster.hub}     cloud / operations center
    EDGE  {cluster.edge}     forward node - LINK chip in the top bar

  Ctrl-C to stop.
""", flush=True)
    stop = False

    def handler(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    try:
        while not stop:
            time.sleep(1)
            if any(p.poll() is not None for p in cluster.procs.values()):
                dead = [n for n, p in cluster.procs.items() if p.poll() is not None]
                print(f"process exited: {dead}", file=sys.stderr)
                for name in dead:
                    print(cluster.logs(name), file=sys.stderr)
                return 1
    finally:
        cluster.stop()
    _ = http
    return 0


if __name__ == "__main__":
    localenv.load()  # keys and SENTINEL_AI_CLOUD reach both nodes
    sys.exit(main())
