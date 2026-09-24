"""The tool catalog: the only things the assistant can do.

Shared by every router (so Jev, the local router and the evals agree on
names) and by the tool registry that executes them. A tool that `writes`
never writes: it returns a draft, and a person confirms it.
"""

from __future__ import annotations

import dataclasses

from ..ops import DECISIONS

__all__ = ["BANDS", "DECISIONS", "TOOLS", "ToolInfo"]
BANDS = ("RED", "AMBER", "GREEN", "UNASSESSED")


@dataclasses.dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    needs_event: bool = False
    writes: bool = False


TOOLS: dict[str, ToolInfo] = {
    t.name: t
    for t in (
        ToolInfo("list_events", "List active conjunctions, optionally only one risk band or those due within a time window"),
        ToolInfo("get_assessment", "Show the collision-risk assessment of one specific conjunction event", needs_event=True),
        ToolInfo("explain_dilution", "Explain whether and why one event's collision probability is diluted", needs_event=True),
        ToolInfo("link_status", "Report the measured state of this node's link to its hub"),
        ToolInfo("sync_queue", "Show what is still waiting to arrive from the hub, in the order it will arrive"),
        ToolInfo(
            "draft_decision",
            "Draft a decision (maneuver, no maneuver, monitor, request tasking) on one event for an operator to confirm",
            needs_event=True,
            writes=True,
        ),
    )
}
