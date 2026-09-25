"""Compact event summaries: what crosses a thin link first (ADR-006, P0).

A summary carries enough to triage - who, when, how bad, how sure - and
nothing that needs a covariance. Measured size, CBOR-encoded: under 256
bytes per event (asserted in tests/sync), so a manifest of every active
event fits in a couple of seconds at 8 kbit/s.

At the bottom of the degradation ladder a summary renders as one line of
text that can be read over a voice net:

    EXSAT-1 X EX-DEB 118 TCA 242017Z MCP 241217Z RED PC 6.3E-3 DIL WC 6.9E-3
"""

from __future__ import annotations

import datetime as dt
import json
import math

from .policy import ConjunctionPolicy

# ADR-006's answer: one event's summary (CBOR, without its `c` record list)
# fits in this many bytes. Asserted over the exercise scenario in tests/sync
# and stated in docs/icd/sync-envelope.md.
SUMMARY_MAX_BYTES = 256

_BAND = {"RED": "R", "AMBER": "A", "GREEN": "G", "UNASSESSED": "U"}
_BAND_BACK = {v: k for k, v in _BAND.items()}
_DC = {"REAL": "R", "DERIVED": "D", "EXERCISE": "X"}
_DC_BACK = {v: k for k, v in _DC.items()}
_CONSEQUENCE = ["ROUTINE", "WATCH", "SERIOUS", "CRITICAL"]
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _log10(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None if value is None else -999.0
    return round(math.log10(value), 3)


def _unlog(value: float | None) -> float | None:
    if value is None:
        return None
    return 0.0 if value <= -999 else 10.0**value


def _epoch(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso).timestamp())


def _iso(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.UTC).isoformat()


def compact_summary(summary: dict, cdms: list[tuple[str, int, int]]) -> dict:
    """cdms: (sha256 prefix, size in bytes, creation epoch) for every CDM of the event."""
    a = summary["assessment"]
    return {
        "e": summary["event_id"],
        "p": [summary["primary"]["id"], (summary["primary"]["name"] or "")[:24]],
        "s": [summary["secondary"]["id"], (summary["secondary"]["name"] or "")[:24]],
        "t": _epoch(summary["tca"]),
        "b": _BAND[summary["band"]],
        "w": None if summary["worst_case_band"] is None else _BAND[summary["worst_case_band"]],
        "pc": _log10(a["pc"]),
        "px": _log10(a["pc_max"]),
        "d": bool(a["dilution_flag"]),
        "r": a["refusal_reason"],
        "md": round(a["miss_distance_m"], 1),
        "rs": round(a["relative_speed_m_s"], 1),
        "h": a["inputs_hash"][:16],
        "dc": _DC[summary["data_class"]],
        # Mission-agnostic triage fields: the only part the sync layer reads.
        "dl": _epoch(summary["mcp"]),
        "q": _CONSEQUENCE.index(summary["consequence"]),
        "c": [[sha, size, created] for sha, size, created in cdms],
    }


def summary_only(compact: dict) -> dict:
    """The P0 part - everything but the CDM list."""
    return {k: v for k, v in compact.items() if k != "c"}


def expand_summary(compact: dict, now: dt.datetime, policy: ConjunctionPolicy) -> dict:
    """Rebuild the API's event-summary shape from a hub-asserted summary.

    The assessment it carries is the hub's, marked as such: no covariance
    travelled, so this node cannot have recomputed it.
    """
    tca = dt.datetime.fromtimestamp(compact["t"], dt.UTC)
    mcp = policy.mcp(tca)
    pc = _unlog(compact["pc"])
    return {
        "event_id": compact["e"],
        "data_class": _DC_BACK[compact["dc"]],
        "primary": {"id": compact["p"][0], "name": compact["p"][1] or None},
        "secondary": {"id": compact["s"][0], "name": compact["s"][1] or None},
        "tca": tca.isoformat(),
        "mcp": mcp.isoformat(),
        "time_to_tca_s": (tca - now).total_seconds(),
        "time_to_mcp_s": (mcp - now).total_seconds(),
        "band": _BAND_BACK[compact["b"]],
        "worst_case_band": None if compact["w"] is None else _BAND_BACK[compact["w"]],
        "consequence": _consequence(compact),
        "needs_attention": compact["b"] in ("R", "A") or compact["w"] == "R",
        "assessment": {
            "method": "REFUSED" if compact["r"] else "FOSTER_ESTES_2D",
            "pc": pc,
            "pc_max": _unlog(compact["px"]),
            "dilution_flag": compact["d"],
            "dilution_margin": None,
            "miss_distance_m": compact["md"],
            "relative_speed_m_s": compact["rs"],
            "hbr_m": None,
            "inputs_hash": compact["h"],
            "refusal_reason": compact["r"],
            "diagnostics": {"asserted_by": compact.get("_origin", "hub")},
        },
        "originator": None,
        "originator_pc": None,
        "cdm_count": len(compact.get("c", [])),
        "latest_cdm_sha256": compact["c"][-1][0] if compact.get("c") else "",
        "latest_message_id": None,
        "verification": "HUB_ASSERTED",
        "voice": voice_line(compact),
    }


# What a malformed summary raises when it is expanded for display.
_UNSHOWABLE = (KeyError, TypeError, ValueError, OverflowError, IndexError, AttributeError, OSError)


def summary_problem(compact: object, now: dt.datetime, policy: ConjunctionPolicy) -> str | None:
    """Why a hub-asserted summary cannot be shown, or None when it can.

    Another node's summary is data this node did not compute. It is stored
    only if this node can expand it into a view the API can serve: one
    unreadable summary must not take down the event list.
    """
    if not isinstance(compact, dict) or not isinstance(compact.get("e"), str) or not compact["e"]:
        return "no event id"
    try:
        shown = expand_summary(compact, now, policy)
        json.dumps(shown, allow_nan=False)
    except _UNSHOWABLE as exc:
        return type(exc).__name__
    if not isinstance(shown["latest_cdm_sha256"], str):
        return "record hash is not text"
    for key in ("pc", "pc_max"):
        value = shown["assessment"][key]
        if value is not None and not 0.0 <= value <= 1.0:
            return "probability outside [0, 1]"
    return None


def _consequence(compact: dict) -> str:
    if compact["b"] == "R":
        return "CRITICAL"
    if compact["b"] == "A" or compact["w"] == "R":
        return "SERIOUS"
    if compact["b"] == "U" or compact["w"] == "A":
        return "WATCH"
    return "ROUTINE"


def _dtg(epoch: int) -> str:
    d = dt.datetime.fromtimestamp(epoch, dt.UTC)
    return f"{d:%d%H%M}Z"


def voice_line(compact: dict, mcp_lead_s: float = ConjunctionPolicy().mcp_lead_time_s) -> str:
    def name(pair):
        return (pair[1] or pair[0]).replace(" (EXERCISE)", "").upper()

    parts = [f"{name(compact['p'])} X {name(compact['s'])}", f"TCA {_dtg(compact['t'])}",
             f"MCP {_dtg(int(compact['t'] - mcp_lead_s))}"]
    if compact["r"]:
        parts.append(f"NO PC {compact['r'].replace('_', ' ')}")
    else:
        parts.append(_BAND_BACK[compact["b"]])
        pc = _unlog(compact["pc"])
        parts.append(f"PC {pc:.1E}".replace("E-0", "E-"))
        if compact["d"]:
            parts.append(f"DIL WC {_unlog(compact['px']):.1E}".replace("E-0", "E-"))
    return " ".join(parts)
