"""System Two: turning a tool's facts into what an operator reads.

Narrators share one protocol. TemplateNarrator writes deterministic prose
and is used whenever the tier policy keeps a language model out (DENIED
link, classified marking, no opt-in). A model narrator paraphrases the
same facts when policy allows. Neither computes, and both are held to the
grounding guard.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Protocol

_SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
METHOD_NAMES = {"FOSTER_ESTES_2D": "Foster-Estes 2D"}
GATE_LABELS = {
    "relative_speed_m_s": "relative speed (m/s)",
    "threshold": "threshold",
    "curvilinear_ratio": "curvilinear ratio",
    "condition_number": "condition number",
    "tca_adjustment_s": "TCA shift (s)",
    "min_eigenvalue": "smallest eigenvalue (m²)",
    "missing_covariance_for": "no covariance for",
    "object_id": "object",
}


class NarratorUnavailable(RuntimeError):
    """A hosted narrator could not answer; `reason` is stable and low-cardinality."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Narrator(Protocol):
    name: str

    async def narrate(self, question: str, tool: str, facts: dict) -> str: ...


@dataclasses.dataclass(frozen=True)
class Narration:
    """One hosted model's answer and what the call cost."""

    text: str
    model: str
    latency_ms: float
    request_bytes: int
    response_bytes: int
    input_tokens: int
    output_tokens: int
    request_id: str | None


# ------------------------------------------------------------ formatting
def format_pc(pc: float) -> str:
    """3.6×10⁻⁵, as the console shows it (web/src/lib/format.ts `sci`)."""
    if pc == 0:
        return "0"
    mantissa, exponent = f"{pc:.1e}".split("e")
    return f"{mantissa}×10{str(int(exponent)).translate(_SUPERSCRIPT)}"


def _num(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:.3g}"


def _value(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _num(value)
    return str(value)


def _pair(facts: dict) -> str:
    return f"{facts['primary']} vs {facts['secondary']}"


def _pc_phrase(facts: dict) -> str:
    if facts["pc"] is None:
        return f"no Pc (refused: {facts['refusal_reason']})"
    return f"Pc {format_pc(facts['pc'])} ({METHOD_NAMES.get(facts['method'], facts['method'])})"


def _mcp_phrase(hours: float) -> str:
    return f"MCP in {hours:.1f} h" if hours >= 0 else f"MCP passed {abs(hours):.1f} h ago"


def event_label(facts: dict) -> str:
    """How an event is named to a router: objects, band, time to act."""
    return f"{_pair(facts)}, {facts['band']}, {_mcp_phrase(facts['time_to_mcp_h'])}"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


# ------------------------------------------------------------- templates
def _list_events(f: dict) -> str:
    where = ""
    if f["filters"].get("band"):
        where += f" in band {f['filters']['band']}"
    if f["filters"].get("window_h") is not None:
        where += f" with MCP within {_num(f['filters']['window_h'])} h"
    if not f["count"]:
        return f"No active events{where}."
    lines = [f"{_plural(f['count'], 'active event')}{where}, soonest commit point first:"]
    for e in f["events"]:
        verified = "" if e["verification"] == "LOCAL" else f" [{e['verification']}]"
        lines.append(f"- {_pair(e)}: {e['band']}, {_pc_phrase(e)}, {_mcp_phrase(e['time_to_mcp_h'])}{verified}")
    return "\n".join(lines)


def _get_assessment(f: dict) -> str:
    parts = [f"{_pair(f)}: {f['band']}."]
    if f["pc"] is None:
        detail = ", ".join(f"{GATE_LABELS.get(k, k)} {_value(v)}" for k, v in (f["refusal_detail"] or {}).items())
        parts.append(f"No Pc: refused, {f['refusal_reason']}" + (f" ({detail})." if detail else "."))
    else:
        worst = "" if f["pc_max"] is None else f"; worst case over covariance scale Pc_max {format_pc(f['pc_max'])}"
        parts.append(f"{_pc_phrase(f)}{worst}.")
        if f["diluted"]:
            parts.append("Diluted: better tracking could raise the Pc.")
    if f["miss_distance_m"] is not None and f["relative_speed_m_s"] is not None:
        hbr = "" if f["hbr_m"] is None else f", HBR {_num(f['hbr_m'])} m"
        parts.append(f"Miss {_num(f['miss_distance_m'])} m at {_num(f['relative_speed_m_s'])} m/s{hbr}.")
    parts.append(f"TCA {f['tca_utc']}; {_mcp_phrase(f['time_to_mcp_h'])} ({f['mcp_utc']}).")
    parts.append(f"{_plural(f['cdm_count'], 'CDM')}; {f['data_class']}; {f['verification']}.")
    return " ".join(parts)


def _explain_dilution(f: dict) -> str:
    pair = _pair(f)
    if not f["applies"]:
        return f"{pair}: dilution does not apply, because there is no Pc (refused: {f['refusal_reason']})."
    if f["k_star"] is None:
        state = "diluted" if f["diluted"] else "not diluted"
        return f"{pair}: {state}, as asserted by the hub. k* is not available until the CDM is assessed here."
    k_star, peak = _num(f["k_star"]), format_pc(f["pc_max"])
    if f["diluted"]:
        return (
            f"{pair}: the Pc is diluted. {_pc_phrase(f)} lies past its peak: scaling the covariance by "
            f"k* = {k_star} gives Pc_max {peak}. Because k* is below one, the low Pc reflects position "
            "uncertainty, not a demonstrated safe miss; better tracking could raise it."
        )
    return (
        f"{pair}: not diluted. {_pc_phrase(f)} is below its peak, which is reached at covariance scale "
        f"k* = {k_star} (Pc_max {peak}). Because k* is above one, better tracking would lower the Pc, not raise it."
    )


def _link_status(f: dict) -> str:
    parts = [f"Link to hub: {f['state']} (measured)."]
    if f.get("rtt_ms") is not None:
        parts.append(f"Round trip {_num(f['rtt_ms'])} ms.")
    if f.get("rate_bytes_per_s") is not None:
        parts.append(f"Throughput {_num(f['rate_bytes_per_s'])} B/s.")
    if f.get("seconds_since_success") is not None:
        parts.append(f"Last successful exchange {_num(f['seconds_since_success'])} s ago.")
    if f.get("failures_in_row"):
        parts.append(f"{_plural(f['failures_in_row'], 'failed exchange')} in a row.")
    if f["state"] == "DENIED":
        parts.append("Working from local data; decisions merge when the link returns.")
    return " ".join(parts)


def _sync_queue(f: dict) -> str:
    if not f["count"]:
        lines = ["Nothing is waiting to arrive from the hub."]
    else:
        lines = [f"{_plural(f['count'], 'item')} waiting from the hub, in arrival order:"]
        for item in f["queue"]:
            eta = "" if item.get("eta_s") is None else f", ETA {_num(item['eta_s'])} s"
            lines.append(f"- {item['event_id']} ({item['class']}): {_num(item['bytes'])} bytes{eta}")
    if f["summary_only"]:
        lines.append("Summary only (the full CDM cannot arrive before its deadline): " + ", ".join(f["summary_only"]))
    return "\n".join(lines)


def _draft_decision(f: dict) -> str:
    against = f["against"]
    basis = f"CDM {against['message_id']}" if against else "the hub's summary (not verified on this node)"
    return (
        f"DRAFT: {f['decision']} on {_pair(f)} ({f['band']}, {_pc_phrase(f)}), against {basis}. "
        "This is not recorded until you confirm it."
    )


TEMPLATES: dict[str, Callable[[dict], str]] = {
    "list_events": _list_events,
    "get_assessment": _get_assessment,
    "explain_dilution": _explain_dilution,
    "link_status": _link_status,
    "sync_queue": _sync_queue,
    "draft_decision": _draft_decision,
}


class TemplateNarrator:
    name = "template"

    async def narrate(self, question: str, tool: str, facts: dict) -> str:
        return TEMPLATES[tool](facts)
