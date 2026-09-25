"""Subcommands beyond the core codec: running a node, exercise data,
demonstration-mode screening.

Kept separate so `sentinel assess` has no import-time dependency on the
web stack.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

from .passes.element_store import default_snapshot

EXIT_REFUSED = 2


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app
    from .obs import configure_logging, log_level

    level = log_level(args.log_level)
    configure_logging(level=level)
    # log_config=None: uvicorn logs through Sentinel's structured handler.
    # No access log: requests are logged at the TLS proxy in front.
    uvicorn.run(
        create_app(), host=args.host, port=args.port,
        log_level=level.lower(), log_config=None, access_log=False,
    )
    return 0


def _exercise_generate(args: argparse.Namespace) -> int:
    from .conjunction.exercise import generate

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    schedule = generate(_utc(args.epoch))
    for item in schedule:
        (out / item.filename).write_text(item.kvn)
    print(f"wrote {len(schedule)} exercise CDMs to {out}")
    return 0


def _utc(text: str) -> dt.datetime:
    """An ISO-8601 time from the command line, or 'now'. Without a timezone it is UTC."""
    when = dt.datetime.now(dt.UTC) if text == "now" else dt.datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=dt.UTC)


def _screen(args: argparse.Namespace) -> int:
    from .passes.element_store import ElementStore
    from .screening.report import report_lines
    from .screening.screen import ScreeningRefused, screen

    store = ElementStore()
    store.load_snapshot(pathlib.Path(args.elements), source=str(args.elements))
    elements = store.latest()
    try:
        result = screen(args.primary, elements, _utc(args.start), args.hours, args.threshold_km)
    except ScreeningRefused as exc:
        print(f"REFUSED {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print("\n".join(report_lines(result, elements)))
    if args.out:
        written = _write_derived_cdms(result, elements, pathlib.Path(args.out))
        print(f"wrote {written} DERIVED CDMs to {args.out}")
    return 0


def _write_derived_cdms(result, elements: dict[int, dict], out: pathlib.Path) -> int:
    from .cdm import emit
    from .screening.derived_cdm import derived_cdms

    out.mkdir(parents=True, exist_ok=True)
    messages = derived_cdms(result, elements, dt.datetime.now(dt.UTC))
    for message in messages:
        (out / f"{message.message_id}.cdm").write_text(emit(message))
    return len(messages)


def register(sub) -> None:
    p = sub.add_parser("serve", help="run a node: API + web console")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--log-level", default=None, help="default: SENTINEL_LOG_LEVEL, else info")
    p.set_defaults(func=_serve)

    ex = sub.add_parser("exercise", help="exercise scenario utilities")
    ex_sub = ex.add_subparsers(dest="exercise_command", required=True)
    g = ex_sub.add_parser("generate", help="write the scripted scenario as KVN files")
    g.add_argument("--out", required=True)
    g.add_argument("--epoch", default="now", help="ISO-8601 scenario start, UTC, or 'now'")
    g.set_defaults(func=_exercise_generate)

    s = sub.add_parser(
        "screen",
        help="demonstration mode: close approaches from public element sets (geometry only, no Pc)",
    )
    s.add_argument("--primary", type=int, required=True, help="NORAD catalog number of the primary")
    s.add_argument("--hours", type=float, default=24.0, help="window length (default 24)")
    s.add_argument("--threshold-km", type=float, default=5.0, help="miss-distance threshold (default 5)")
    s.add_argument("--elements", default=str(default_snapshot()), help="CelesTrak OMM JSON array")
    s.add_argument("--start", default="now", help="ISO-8601 window start, UTC, or 'now'")
    s.add_argument("--out", default=None, help="write each approach as a DERIVED CDM (KVN) into this directory")
    s.set_defaults(func=_screen)
