"""Run DDIL scenarios against a real two-node cluster.

    python -m harness.run denied [limited intermittent degraded recovery | all] [--denial-s 20]

Writes harness/results/<scenario>.json and exits non-zero if any assertion
fails. `python -m harness.report` turns the results into docs/ddil-results.md.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import traceback

from .scenarios import SCENARIOS, Result

RESULTS = pathlib.Path(__file__).resolve().parent / "results"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="+", choices=[*SCENARIOS, "all"])
    parser.add_argument("--denial-s", type=float, default=20.0)
    args = parser.parse_args()
    names = list(SCENARIOS) if "all" in args.scenarios else args.scenarios
    RESULTS.mkdir(exist_ok=True)
    failed = False
    for name in names:
        print(f"=== {name.upper()}", flush=True)
        try:
            result = SCENARIOS[name](args.denial_s) if name == "denied" else SCENARIOS[name]()
        except Exception as exc:  # noqa: BLE001 - a crashed scenario is a failed scenario
            result = Result(name.upper())
            result.check("scenario ran to completion", False, f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
        for a in result.assertions:
            print(f"  [{'PASS' if a['passed'] else 'FAIL'}] {a['name']}" + (f" - {a['detail']}" if a["detail"] else ""))
        print(f"  metrics: {json.dumps(result.metrics, default=str)[:600]}")
        (RESULTS / f"{name}.json").write_text(json.dumps(result.to_dict(), indent=1, default=str))
        failed |= not result.passed
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
