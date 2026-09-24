#!/usr/bin/env python3
"""Snapshot a CelesTrak GP group as OMM JSON into fixtures/omm/, with provenance.

    uv run python scripts/fetch_omm.py resource

The snapshot is what the pass module and its tests run on: public data,
pinned by sha256, so results are reproducible offline. Refresh it
deliberately; never fetch at test or run time.
"""

import datetime as dt
import hashlib
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures" / "omm"
URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=json"


def main(group: str) -> None:
    url = URL.format(group=group)
    request = urllib.request.Request(url, headers={"User-Agent": "Sentinel (snapshot script)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    records = json.loads(raw)
    retrieved = dt.datetime.now(dt.UTC).replace(microsecond=0)
    path = OUT / f"celestrak-{group}-{retrieved:%Y%m%d}.json"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with (OUT / "SHA256SUMS").open("a") as sums:
        sums.write(f"{digest}  {path.name}\n")
    with (OUT / "PROVENANCE.md").open("a") as prov:
        prov.write(f"| `{path.name}` | {url} | {retrieved.isoformat()} | {len(records)} | `{digest[:16]}` |\n")
    print(f"wrote {path.relative_to(ROOT)}: {len(records)} objects, sha256 {digest[:16]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "resource")
