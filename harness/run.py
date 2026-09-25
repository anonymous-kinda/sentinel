"""Run DDIL scenarios against a real two-node cluster.

    python -m harness.run denied [limited intermittent degraded recovery opsec | all]
                          [--denial-s 20] [--limited-runs 5]

Writes harness/results/<scenario>.json and exits non-zero if any assertion
fails. `python -m harness.report` turns the results into docs/ddil-results.md.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import traceback

from .scenarios import LIMITED_RUNS, SCENARIOS, Result

RESULTS = pathlib.Path(__file__).resolve().parent / "results"


def print_result(result: Result) -> None:
    for a in result.assertions:
        print(f"  [{'PASS' if a['passed'] else 'FAIL'}] {a['name']}" + (f" - {a['detail']}" if a["detail"] else ""))
    print(f"  metrics: {json.dumps(result.metrics, default=str)[:600]}")


def _at_least_one(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("at least 1")
    return value


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m harness.run")
    parser.add_argument("scenarios", nargs="+", choices=[*SCENARIOS, "all"])
    parser.add_argument("--denial-s", type=float, default=20.0, help="DENIED: how long the link stays cut")
    parser.add_argument("--limited-runs", type=_at_least_one, default=LIMITED_RUNS,
                        help="LIMITED: runs per mode behind each median")
    return parser.parse_args(argv)


def options_for(name: str, args: argparse.Namespace) -> dict:
    """The keyword arguments scenario `name` takes from the command line."""
    return {
        "denied": {"denial_s": args.denial_s},
        "limited": {"runs_per_mode": args.limited_runs},
    }.get(name, {})


def main() -> int:
    args = parse()
    names = list(SCENARIOS) if "all" in args.scenarios else args.scenarios
    RESULTS.mkdir(exist_ok=True)
    failed = False
    for name in names:
        print(f"=== {name.upper()}", flush=True)
        try:
            result = SCENARIOS[name](**options_for(name, args))
        except Exception as exc:  # noqa: BLE001 - a crashed scenario is a failed scenario
            result = Result(name.upper())
            result.check("scenario ran to completion", False, f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
        print_result(result)
        (RESULTS / f"{name}.json").write_text(json.dumps(result.to_dict(), indent=1, default=str))
        failed |= not result.passed
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
