"""Subcommands beyond the core codec: running a node, exercise data.

Kept separate so `sentinel assess` has no import-time dependency on the
web stack.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level=args.log_level)
    return 0


def _exercise_generate(args: argparse.Namespace) -> int:
    from .conjunction.exercise import generate

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    epoch = dt.datetime.now(dt.UTC) if args.epoch == "now" else dt.datetime.fromisoformat(args.epoch)
    for item in generate(epoch):
        (out / item.filename).write_text(item.kvn)
    print(f"wrote {len(generate(epoch))} exercise CDMs to {out}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("serve", help="run a node: API + web console")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--log-level", default="info")
    p.set_defaults(func=_serve)

    ex = sub.add_parser("exercise", help="exercise scenario utilities")
    ex_sub = ex.add_subparsers(dest="exercise_command", required=True)
    g = ex_sub.add_parser("generate", help="write the scripted scenario as KVN files")
    g.add_argument("--out", required=True)
    g.add_argument("--epoch", default="now", help="ISO-8601 scenario start, or 'now'")
    g.set_defaults(func=_exercise_generate)
