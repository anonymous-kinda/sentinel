"""Command-line interface.

    sentinel assess FILE.cdm [--hbr M] [--json]
    sentinel cdm parse FILE.cdm          # structure + admission warnings as JSON
    sentinel cdm emit FILE.cdm           # normalised KVN on stdout

Exit status follows the ingest policy: 0 when a message was assessed (a
refusal is still an assessment), 2 when it was rejected as wrong, 1 on
usage or I/O errors.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from . import __version__
from .cdm import CdmParseError, CdmRejected, emit, parse_bytes, to_conjunction
from .risk import assess
from .risk.types import Method

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REJECTED = 2


def _read(path: str) -> bytes:
    return pathlib.Path(path).read_bytes()


def _cmd_assess(args: argparse.Namespace) -> int:
    message = parse_bytes(_read(args.file))
    conversion = to_conjunction(message, hbr_override_m=args.hbr)
    result = assess(conversion.conjunction)

    payload: dict[str, Any] = {
        "message_id": message.message_id,
        "tca": message.tca.isoformat(),
        "objects": [message.object_name(0), message.object_name(1)],
        "hbr_source": conversion.hbr_source,
        "warnings": [w.__dict__ for w in conversion.warnings],
        "originator_pc": message.collision_probability,
        "assessment": result.to_dict(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return EXIT_OK

    a = result
    print(f"{payload['message_id']}  TCA {payload['tca']}")
    print(f"  {payload['objects'][0]}  vs  {payload['objects'][1]}")
    print(f"  miss {a.miss_distance_m:,.1f} m   relative speed {a.relative_speed_m_s:,.1f} m/s")
    if a.method is Method.REFUSED:
        assert a.refusal_reason is not None  # assess() never refuses without a reason
        print(f"  REFUSED  {a.refusal_reason.value}")
        for key, value in a.diagnostics.items():
            print(f"    {key}: {value}")
    else:
        print(f"  Pc      {a.pc:.4e}   ({a.method.value})")
        print(f"  Pc max  {a.pc_max:.4e}   k* = {a.diagnostics['k_star']:.3g}")
        if a.dilution_flag:
            print("  DILUTED: this Pc may reflect ignorance rather than safety; see Pc max")
    if message.collision_probability is not None:
        print(f"  originator-asserted Pc {message.collision_probability:.4e} (not Sentinel's)")
    for w in conversion.warnings:
        print(f"  warning {w.code}: {w.detail}")
    print(f"  inputs {a.inputs_hash[:16]}")
    return EXIT_OK


def _cmd_cdm_parse(args: argparse.Namespace) -> int:
    from .cdm import validate

    message = parse_bytes(_read(args.file))
    warnings = validate(message)
    print(
        json.dumps(
            {
                "message_id": message.message_id,
                "originator": message.originator,
                "tca": message.tca.isoformat(),
                "objects": [message.object_designator(0), message.object_designator(1)],
                "hbr_from_comment_m": message.hbr_from_comment_m(),
                "warnings": [w.__dict__ for w in warnings],
            },
            indent=2,
        )
    )
    return EXIT_OK


def _cmd_cdm_emit(args: argparse.Namespace) -> int:
    sys.stdout.write(emit(parse_bytes(_read(args.file))))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel", description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", action="version", version=f"sentinel {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("assess", help="assess one CDM")
    p.add_argument("file")
    p.add_argument("--hbr", type=float, default=None, help="combined hard-body radius, metres")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_assess)

    cdm = sub.add_parser("cdm", help="CDM codec utilities")
    cdm_sub = cdm.add_subparsers(dest="cdm_command", required=True)
    cp = cdm_sub.add_parser("parse")
    cp.add_argument("file")
    cp.set_defaults(func=_cmd_cdm_parse)
    ce = cdm_sub.add_parser("emit")
    ce.add_argument("file")
    ce.set_defaults(func=_cmd_cdm_emit)

    _register_extensions(sub)
    return parser


def _register_extensions(sub) -> None:
    """Subcommands contributed by other packages (server, sync, passes)."""
    from . import cli_ext

    cli_ext.register(sub)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or EXIT_OK)
    except CdmRejected as exc:
        print(f"REJECTED {exc}", file=sys.stderr)
        return EXIT_REJECTED
    except (CdmParseError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
