#!/usr/bin/env python3
"""Write docs/icd/openapi.json from the node's FastAPI app.

    uv run python scripts/export_openapi.py        (or: make openapi)

The node is built with every module registered (the assistant on), no
background tasks, no network and a throwaway state directory, so the spec
depends on the routes alone. Output is canonical JSON (sorted keys, two-space
indent, trailing newline): the same code always gives the same bytes, and
tests/docs/test_openapi_current.py fails when the committed file is stale.
"""

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.api import create_app  # noqa: E402
from sentinel.api.settings import Settings  # noqa: E402
from sentinel.obs import configure_logging, get_logger  # noqa: E402

OUTPUT = ROOT / "docs" / "icd" / "openapi.json"

log = get_logger("sentinel.scripts.export_openapi")


def export() -> dict:
    """The OpenAPI document of a node with every module registered."""
    with tempfile.TemporaryDirectory(prefix="sentinel-openapi-") as var_dir:
        settings = Settings(
            node_id="icd",
            exercise=False,
            library=False,
            web_dist=None,
            var_dir=var_dir,
            ai=True,
            ai_cloud=False,
        )
        return create_app(settings, start_background=False).openapi()


def render(spec: dict) -> str:
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def drift(committed: str, fresh: str) -> list[str]:
    """What differs between a committed export and a fresh one: each
    top-level section and each path, by name. Empty when identical."""
    if committed == fresh:
        return []
    old, new = json.loads(committed), json.loads(fresh)
    problems = [
        f"{key} differs"
        for key in sorted(old.keys() | new.keys())
        if key != "paths" and old.get(key) != new.get(key)
    ]
    old_paths, new_paths = old.get("paths", {}), new.get("paths", {})
    problems += [
        f"paths.{path} differs"
        for path in sorted(old_paths.keys() | new_paths.keys())
        if old_paths.get(path) != new_paths.get(path)
    ]
    return problems or ["formatting differs"]


def main() -> int:
    spec = export()
    OUTPUT.write_text(render(spec))
    log.info("OpenAPI document written", path=str(OUTPUT.relative_to(ROOT)), paths=len(spec["paths"]))
    return 0


if __name__ == "__main__":
    configure_logging()
    sys.exit(main())
