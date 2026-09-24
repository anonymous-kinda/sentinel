"""The assistant's tools: deterministic code over this node's services.

A tool returns facts - the evidence an answer may cite, and nothing more.
Every number in it comes from the code the validation report covers; a
router only picks the tool and a narrator only phrases the result.

A tool that `writes` (catalog.TOOLS) returns a draft. Nothing is recorded
until a person confirms it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from ..ops import same_record
from .catalog import BANDS, DECISIONS

# Diagnostics that explain a refusal: the value that tripped a gate and
# the gate's threshold. The rest of the diagnostics are engine internals.
REFUSAL_FACTS = (
    "threshold",
    "relative_speed_m_s",
    "curvilinear_ratio",
    "condition_number",
    "tca_adjustment_s",
    "min_eigenvalue",
    "missing_covariance_for",
    "object_id",
)


class ToolError(ValueError):
    """A call the tool cannot serve. `code` is stable; the orchestrator
    turns it into a question back to the operator."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _hours(seconds: float) -> float:
    return round(seconds / 3600, 1)


def _utc(iso: str) -> str:
    """Dates are formatted here, by code; no model is asked to."""
    return f"{dt.datetime.fromisoformat(iso).astimezone(dt.UTC):%Y-%m-%d %H:%MZ}"


def event_facts(summary: dict) -> dict:
    """One event, as the assistant sees it in a list."""
    a = summary["assessment"]
    return {
        "event_id": summary["event_id"],
        "primary": summary["primary"]["name"] or summary["primary"]["id"],
        "secondary": summary["secondary"]["name"] or summary["secondary"]["id"],
        "secondary_id": summary["secondary"]["id"],
        "band": summary["band"],
        "method": a["method"],
        "pc": a["pc"],
        "refusal_reason": a["refusal_reason"],
        "time_to_mcp_h": _hours(summary["time_to_mcp_s"]),
        "data_class": summary["data_class"],
        "verification": summary.get("verification", "LOCAL"),
    }


class ToolRegistry:
    def __init__(self, conjunctions, ops, link, sync_status: Callable[[], dict]):
        """`conjunctions`: ConjunctionService; `ops`: OpsService;
        `link`: LinkMonitor; `sync_status`: the /api/sync view."""
        self.conjunctions = conjunctions
        self.ops = ops
        self.link = link
        self.sync_status = sync_status
        self._handlers: dict[str, Callable[[dict], dict]] = {
            "list_events": self._list_events,
            "get_assessment": self._get_assessment,
            "explain_dilution": self._explain_dilution,
            "link_status": self._link_status,
            "sync_queue": self._sync_queue,
            "draft_decision": self._draft_decision,
        }

    def execute(self, tool: str, args: dict) -> dict:
        handler = self._handlers.get(tool)
        if handler is None:
            raise ToolError("unknown_tool", tool)
        return handler(args)

    def _summary(self, args: dict) -> dict:
        event_id = args.get("event_id")
        if not event_id:
            raise ToolError("missing_event")
        detail = self.conjunctions.event_detail(event_id)
        if detail is None:
            raise ToolError("unknown_event", event_id)
        return detail["summary"]

    # ------------------------------------------------------------- handlers
    def _list_events(self, args: dict) -> dict:
        band = args.get("band")
        if band is not None and band not in BANDS:
            raise ToolError("invalid_band", band)
        window_h = args.get("window_h")
        events = [event_facts(s) for s in self.conjunctions.list_events("active")]
        if band is not None:
            events = [e for e in events if e["band"] == band]
        if window_h is not None:
            events = [e for e in events if e["time_to_mcp_h"] <= window_h]
        events.sort(key=lambda e: e["time_to_mcp_h"])
        return {"filters": {"band": band, "window_h": window_h}, "count": len(events), "events": events}

    def _get_assessment(self, args: dict) -> dict:
        s = self._summary(args)
        a = s["assessment"]
        refused = a["method"] == "REFUSED"
        return {
            **event_facts(s),
            "pc_max": a["pc_max"],
            "diluted": a["dilution_flag"],
            "miss_distance_m": a["miss_distance_m"],
            "relative_speed_m_s": a["relative_speed_m_s"],
            "hbr_m": a["hbr_m"],
            "tca_utc": _utc(s["tca"]),
            "mcp_utc": _utc(s["mcp"]),
            "time_to_tca_h": _hours(s["time_to_tca_s"]),
            "cdm_count": s["cdm_count"],
            "refusal_detail": {k: v for k, v in a["diagnostics"].items() if k in REFUSAL_FACTS} if refused else None,
        }

    def _explain_dilution(self, args: dict) -> dict:
        s = self._summary(args)
        a = s["assessment"]
        facts = event_facts(s)
        if a["method"] == "REFUSED":
            return {**facts, "applies": False}
        return {
            **facts,
            "applies": True,
            "diluted": a["dilution_flag"],
            "k_star": a["diagnostics"].get("k_star"),
            "pc_max": a["pc_max"],
        }

    def _link_status(self, args: dict) -> dict:
        return self.link.snapshot()

    def _sync_queue(self, args: dict) -> dict:
        status = self.sync_status()
        queue = status.get("queue", [])
        return {"count": len(queue), "queue": queue, "summary_only": status.get("summary_only", [])}

    def _draft_decision(self, args: dict) -> dict:
        s = self._summary(args)
        decision = args.get("decision")
        if not decision:
            raise ToolError("missing_decision")
        if decision not in DECISIONS:
            raise ToolError("invalid_decision", decision)
        return {
            **event_facts(s),
            "draft": True,
            "decision": decision,
            "against": self.conjunctions.current_ref(s["event_id"]),
        }

    # ---------------------------------------------------------------- writes
    async def record_decision(self, draft: dict, author: str, rationale: str, provenance: dict) -> dict:
        """Write a confirmed draft as a signed DECISION, against the CDM it
        was drafted on. A draft on a superseded CDM must be redrafted."""
        current, against = self.conjunctions.current_ref(draft["event_id"]), draft["against"]
        if not (current and against and same_record(current["cdm_sha256"], against["cdm_sha256"])):
            raise ToolError("stale_draft", draft["event_id"])
        body = {"decision": draft["decision"], "rationale": rationale, "drafted_by": provenance}
        return await self.ops.append(draft["event_id"], "DECISION", body, author, event_ref=draft["against"])
