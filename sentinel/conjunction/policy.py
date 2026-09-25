"""Operator policy: risk bands, maneuver commit point, triage mapping.

Every number here is an operator assumption, not physics, and is labelled
as such wherever it is displayed. NASA CARA's published practice is a
maneuver-planning threshold of Pc > 1e-4 (red), with 1e-7..1e-4 treated as
a watch band; some missions act at 1e-5. Sentinel's defaults follow that,
with AMBER starting at 1e-5.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum

from ..risk.types import AssessedConjunction, Method
from ..triage import Consequence, PriorityClass, TriageKey


class Band(enum.StrEnum):
    RED = "RED"
    AMBER = "AMBER"
    GREEN = "GREEN"
    UNASSESSED = "UNASSESSED"


@dataclasses.dataclass(frozen=True)
class ConjunctionPolicy:
    red_pc: float = 1e-4
    amber_pc: float = 1e-5
    # Maneuver commit point = TCA minus the time an operator needs to plan,
    # approve, uplink and execute. Per asset in reality; one default here.
    mcp_lead_time_s: float = 8 * 3600.0
    # Full records for events whose MCP falls inside this window sync first.
    urgent_window_s: float = 72 * 3600.0

    def band_for(self, pc: float | None) -> Band:
        if pc is None:
            return Band.UNASSESSED
        if pc >= self.red_pc:
            return Band.RED
        if pc >= self.amber_pc:
            return Band.AMBER
        return Band.GREEN

    def mcp(self, tca: dt.datetime) -> dt.datetime:
        return tca - dt.timedelta(seconds=self.mcp_lead_time_s)


@dataclasses.dataclass(frozen=True)
class Triage:
    band: Band
    worst_case_band: Band | None     # from pc_max, only when diluted
    consequence: Consequence
    mcp: dt.datetime
    needs_attention: bool


def triage(result: AssessedConjunction, tca: dt.datetime, policy: ConjunctionPolicy) -> Triage:
    """Reduce an assessment to band, worst case and consequence.

    A diluted event is banded by its Pc *and* carries the band its worst
    case would have. The worst case drives attention (an operator should
    look), never action on its own: CARA's R&D finding is that maximum Pc
    is not sufficient as a stand-alone risk parameter.
    """
    band = policy.band_for(result.pc if result.method is Method.FOSTER_ESTES_2D else None)
    worst = policy.band_for(result.pc_max) if result.dilution_flag else None

    if band is Band.RED:
        consequence = Consequence.CRITICAL
    elif band is Band.AMBER or worst is Band.RED:
        consequence = Consequence.SERIOUS
    elif band is Band.UNASSESSED or worst is Band.AMBER:
        consequence = Consequence.WATCH
    else:
        consequence = Consequence.ROUTINE

    return Triage(
        band=band,
        worst_case_band=worst,
        consequence=consequence,
        mcp=policy.mcp(tca),
        needs_attention=consequence >= Consequence.SERIOUS,
    )


def triage_key(
    event_id: str, t: Triage, now: dt.datetime, policy: ConjunctionPolicy, full_record: bool
) -> TriageKey:
    """Unused: nothing calls it. The sync agent assigns classes itself, from
    the deadline and consequence a summary carries (SyncAgent._wanted in
    sentinel/sync/agent.py), by a rule that differs from this one: no record
    is P0_SUMMARY, and superseded records are P4_BULK."""
    if not full_record:
        klass = PriorityClass.P0_SUMMARY
    elif t.consequence >= Consequence.SERIOUS and (t.mcp - now).total_seconds() <= policy.urgent_window_s:
        klass = PriorityClass.P1_URGENT
    else:
        klass = PriorityClass.P2_ROUTINE
    return TriageKey(event_id, klass, t.mcp, t.consequence)
