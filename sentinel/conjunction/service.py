"""Conjunction service: ingest, event grouping, assessment, views.

Ingest follows the admission policy end to end:

    raw bytes --sha256--> duplicate?         -> no-op (idempotent)
              --parse---> not a CDM?         -> quarantine PARSE_ERROR
              --validate> wrong?             -> quarantine with the reason
              --group---> event id
              --assess--> AssessedConjunction (refusal is a result)
              --publish-> cdm.accepted.<event_id>

Everything the API returns is computed from the stored raw bytes by the
same engine the tests validate, so the UI cannot show a number the
validation report does not cover.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import hashlib
import json
import math

import numpy as np

from .. import __version__
from ..bus import Bus, subjects
from ..cdm import CdmParseError, CdmRejected, parse_bytes, to_conjunction
from ..cdm.model import CdmMessage
from ..clock import Clock
from ..risk.encounter import build_encounter_plane, curvilinear_check, pc_curve
from ..risk.engine import assess, finite_eigenvalues
from ..risk.types import AssessedConjunction, AssessmentConfig, Method, RefusalReason
from .policy import ConjunctionPolicy, triage
from .store import CdmRow, ConjunctionStore, EventRow
from .summaries import compact_summary, disagreements, expand_summary, record_hashes
from .trajectory import encounter_arcs_ecef

EVENT_TCA_WINDOW_S = 60.0
EXERCISE_ORIGINATOR = "SENTINEL-EXERCISE"
SCREENING_ORIGINATOR = "SENTINEL-SCREENING"
DATA_CLASSES = ("REAL", "DERIVED", "EXERCISE")
# Sentinel's own generators mark their messages at the source. The mark
# decides the data class, whatever route the message arrived by.
ORIGINATOR_DATA_CLASS = {EXERCISE_ORIGINATOR: "EXERCISE", SCREENING_ORIGINATOR: "DERIVED"}


@dataclasses.dataclass(frozen=True)
class IngestResult:
    status: str                 # accepted | duplicate | rejected
    sha256: str
    event_id: str | None = None
    code: str | None = None
    detail: str | None = None
    warnings: tuple[dict, ...] = ()


def _config_hash(config: AssessmentConfig) -> str:
    payload = json.dumps(dataclasses.asdict(config), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


class ConjunctionService:
    def __init__(
        self,
        store: ConjunctionStore,
        bus: Bus,
        clock: Clock,
        policy: ConjunctionPolicy | None = None,
        engine_config: AssessmentConfig | None = None,
        node_id: str = "standalone",
    ):
        self.node_id = node_id
        self.store = store
        self.bus = bus
        self.clock = clock
        self.policy = policy or ConjunctionPolicy()
        self.engine_config = engine_config or AssessmentConfig()
        self.engine_version = f"{__version__}+{_config_hash(self.engine_config)}"

    # ------------------------------------------------------------------ ingest
    async def ingest(
        self,
        raw: bytes,
        source: str,
        data_class: str = "REAL",
        event_id: str | None = None,
    ) -> IngestResult:
        """Admit one CDM. `event_id` is passed when another node already
        assigned the event identity (edge fetching from the hub); the edge
        must not re-derive it, or updates fetched out of order would split
        one event into two."""
        if data_class not in DATA_CLASSES:
            raise ValueError(f"unknown data class {data_class!r}")
        sha = hashlib.sha256(raw).hexdigest()
        if self.store.has_cdm(sha):
            return IngestResult("duplicate", sha)

        try:
            message = parse_bytes(raw)
            conversion = to_conjunction(message)
        except CdmParseError as exc:
            return await self._reject(sha, raw, "PARSE_ERROR", str(exc), source)
        except CdmRejected as exc:
            return await self._reject(sha, raw, exc.code, str(exc), source)
        except (ValueError, KeyError) as exc:
            return await self._reject(sha, raw, "UNREADABLE", str(exc), source)

        data_class = ORIGINATOR_DATA_CLASS.get((message.originator or "").upper(), data_class)

        event = self._event_for(message, data_class, event_id)
        warnings = [dataclasses.asdict(w) for w in conversion.warnings]
        self.store.add_cdm(
            CdmRow(
                sha256=sha,
                raw=raw,
                message_id=message.message_id,
                originator=message.originator,
                creation_date=None if message.creation_date is None else message.creation_date.isoformat(),
                tca=message.tca.isoformat(),
                primary_id=event.primary_id,
                secondary_id=event.secondary_id,
                event_id=event.event_id,
                data_class=data_class,
                source=source,
                received_at=self.clock.now().isoformat(),
                warnings=warnings,
                hbr_source=conversion.hbr_source,
            )
        )
        self._assess_sha(sha, message)
        summary = self.event_summary(event.event_id)
        await self.bus.publish(
            subjects.cdm_accepted(self.node_id, event.event_id),
            json.dumps(summary, default=str).encode(),
            {"Sentinel-Kind": "cdm.accepted", "Sentinel-Data-Class": data_class},
        )
        return IngestResult("accepted", sha, event.event_id, warnings=tuple(warnings))

    async def _reject(self, sha: str, raw: bytes, code: str, detail: str, source: str) -> IngestResult:
        self.store.quarantine(sha, raw, code, detail, source)
        await self.bus.publish(
            subjects.cdm_rejected(self.node_id),
            json.dumps({"sha256": sha, "code": code, "detail": detail, "source": source}).encode(),
            {"Sentinel-Kind": "cdm.rejected"},
        )
        return IngestResult("rejected", sha, code=code, detail=detail)

    def _event_for(self, message: CdmMessage, data_class: str, event_id: str | None = None) -> EventRow:
        """Group CDM updates into events: same object pair, same data class,
        TCA within 60 s.

        CCSDS 508.0-B-1 has no event identifier, so the rule has to be
        explicit. Identity is assigned where a CDM is first ingested and
        travels with it; downstream nodes never re-derive it.

        An event holds one data class. A screening CDM (DERIVED, geometry
        only) for the pair of a REAL event would otherwise become its latest
        CDM, and its refusal would replace the real Pc.
        """
        pri = message.object_designator(0) or "OBJECT1"
        sec = message.object_designator(1) or "OBJECT2"
        tca = message.tca
        if event_id is not None:
            existing = self.store.event(event_id)
            if existing is not None:
                return existing
            row = EventRow(event_id, pri, message.object_name(0), sec, message.object_name(1), tca.isoformat(), data_class)
            self.store.add_event(row)
            return row
        for ev in self.store.events_for_pair(pri, sec):
            same_class = ev.data_class == data_class
            if same_class and abs((dt.datetime.fromisoformat(ev.tca_ref) - tca).total_seconds()) <= EVENT_TCA_WINDOW_S:
                return ev
        row = EventRow(
            event_id=self._new_event_id(pri, sec, tca, data_class),
            primary_id=pri,
            primary_name=message.object_name(0),
            secondary_id=sec,
            secondary_name=message.object_name(1),
            tca_ref=tca.isoformat(),
            data_class=data_class,
        )
        self.store.add_event(row)
        return row

    def _new_event_id(self, pri: str, sec: str, tca: dt.datetime, data_class: str) -> str:
        """`<pri>-<sec>-<TCA to the second>`. A screening TCA often falls in
        the same second as the REAL one, so when an event of another class
        already has the id, the new one carries its data class as well."""
        event_id = f"{pri}-{sec}-{tca:%Y%m%dT%H%M%S}"
        return event_id if self.store.event(event_id) is None else f"{event_id}-{data_class}"

    # --------------------------------------------------------------- assessment
    @functools.lru_cache(maxsize=4096)  # noqa: B019 - bounded, keyed by content hash
    def _parsed(self, sha: str):
        row = self.store.cdm(sha)
        message = parse_bytes(row.raw)
        return message, to_conjunction(message)

    def _assess_sha(self, sha: str, message: CdmMessage | None = None) -> dict:
        cached = self.store.assessment(sha, self.engine_version)
        if cached is not None:
            return cached
        _, conversion = self._parsed(sha)
        result = assess(conversion.conjunction, self.engine_config).to_dict()
        self.store.put_assessment(sha, self.engine_version, result)
        return result

    def reassess_all(self) -> int:
        """Recompute every assessment from raw bytes under the current engine."""
        count = 0
        for row in self.store.all_cdms():
            self._assess_sha(row.sha256)
            count += 1
        return count

    # --------------------------------------------------------------------- views
    def _latest(self, event_id: str) -> CdmRow | None:
        rows = self.store.cdms_for_event(event_id)
        return rows[-1] if rows else None

    def event_summary(self, event_id: str) -> dict:
        event = self.store.event(event_id)
        rows = self.store.cdms_for_event(event_id)
        latest = rows[-1]
        a = self._assess_sha(latest.sha256)
        message, _ = self._parsed(latest.sha256)
        tca = message.tca
        result = _from_dict(a)
        t = triage(result, tca, self.policy)
        now = self.clock.now()
        return {
            "event_id": event_id,
            "data_class": latest.data_class,
            "primary": {"id": event.primary_id, "name": event.primary_name},
            "secondary": {"id": event.secondary_id, "name": event.secondary_name},
            "tca": tca.isoformat(),
            "mcp": t.mcp.isoformat(),
            "time_to_tca_s": (tca - now).total_seconds(),
            "time_to_mcp_s": (t.mcp - now).total_seconds(),
            "band": t.band.value,
            "worst_case_band": None if t.worst_case_band is None else t.worst_case_band.value,
            "consequence": t.consequence.name,
            "needs_attention": t.needs_attention,
            "assessment": a,
            "originator": message.originator,
            "originator_pc": message.collision_probability,
            "cdm_count": len(rows),
            "latest_cdm_sha256": latest.sha256,
            "latest_message_id": latest.message_id,
        }

    def list_events(self, scope: str = "active") -> list[dict]:
        """scope: active (TCA in the future), past, or all.

        On an edge node the list also carries events known only from the
        hub's summaries (verification HUB_ASSERTED) until their CDMs arrive
        and are re-assessed here.
        """
        now = self.clock.now()
        remote = self.store.remote_summaries()
        out = []
        local_ids = set()
        for ev in self.store.events():
            if not self.store.cdms_for_event(ev.event_id):
                continue
            local_ids.add(ev.event_id)
            summary = self.event_summary(ev.event_id)
            summary["verification"] = self._verification(summary, remote.get(ev.event_id))
            future = dt.datetime.fromisoformat(summary["tca"]) > now
            if scope == "all" or (scope == "active") == future:
                out.append(summary)
        for event_id, compact in remote.items():
            if event_id in local_ids:
                continue
            summary = expand_summary(compact, now, self.policy)
            future = dt.datetime.fromisoformat(summary["tca"]) > now
            if scope == "all" or (scope == "active") == future:
                out.append(summary)
        if scope == "active":
            out.sort(key=lambda s: (s["time_to_mcp_s"], -_consequence_rank(s)))
        else:
            out.sort(key=lambda s: s["tca"], reverse=True)
        return out

    def _verification(self, summary: dict, remote: dict | None) -> str:
        """LOCAL: this node's own data - no hub summary, or a CDM newer than
        any the hub listed. UPDATING: the hub's latest CDM is not here yet.
        VERIFIED: what this node shows is its own assessment of a record the
        hub listed, and it is the result the hub asserted, field for field
        (`disagreements`). MISMATCH: it is not - flag it."""
        if remote is None:
            return "LOCAL"
        listed = record_hashes(remote)
        if listed and not self.store.has_cdm_prefix(listed[-1]):
            return "UPDATING"
        latest = summary["latest_cdm_sha256"]
        if listed and not any(latest.startswith(sha16) for sha16 in listed):
            return "LOCAL"
        return "MISMATCH" if disagreements(summary, remote) else "VERIFIED"

    def current_ref(self, event_id: str) -> dict | None:
        """What a decision about this event is made against, right now. For
        an event known only from the hub's summary, that is the record the
        hub asserted (the leading hex digits of its sha256), so a decision
        made on the summary is flagged when a different CDM arrives."""
        latest = self._latest(event_id)
        if latest is None:
            return self._asserted_ref(event_id)
        a = self._assess_sha(latest.sha256)
        return {"cdm_sha256": latest.sha256, "inputs_hash": a["inputs_hash"], "message_id": latest.message_id}

    def _asserted_ref(self, event_id: str) -> dict | None:
        remote = self.store.remote_summaries().get(event_id)
        listed = [] if remote is None else record_hashes(remote)
        if not listed:
            return None
        return {"cdm_sha256": listed[-1], "inputs_hash": remote.get("h"), "message_id": None,
                "asserted_by": remote.get("_origin")}

    def manifest(self) -> list[dict]:
        """Compact summaries of every active event, for edges (P0)."""
        out = []
        for summary in self.list_events("active"):
            if summary.get("verification") in (None, "LOCAL"):
                rows = self.store.cdms_for_event(summary["event_id"])
                out.append(
                    compact_summary(
                        summary,
                        [(r.sha256[:16], len(r.raw), _epoch(r.creation_date or r.received_at)) for r in rows],
                    )
                )
        return out

    def event_detail(self, event_id: str) -> dict | None:
        if self.store.event(event_id) is None or not self.store.cdms_for_event(event_id):
            remote = self.store.remote_summaries().get(event_id)
            if remote is None:
                return None
            # Known only from the hub's summary: show it, marked, with no history.
            return {
                "summary": expand_summary(remote, self.clock.now(), self.policy),
                "history": [],
                "engine_version": self.engine_version,
                "policy": dataclasses.asdict(self.policy),
                "asserted_by": remote.get("_origin"),
            }
        history = []
        for row in self.store.cdms_for_event(event_id):
            message, conversion = self._parsed(row.sha256)
            history.append(
                {
                    "sha256": row.sha256,
                    "message_id": row.message_id,
                    "creation_date": row.creation_date,
                    "received_at": row.received_at,
                    "source": row.source,
                    "tca": message.tca.isoformat(),
                    "originator_pc": message.collision_probability,
                    "hbr_source": row.hbr_source,
                    "warnings": row.warnings,
                    "assessment": self._assess_sha(row.sha256),
                }
            )
        summary = self.event_summary(event_id)
        summary["verification"] = self._verification(summary, self.store.remote_summaries().get(event_id))
        return {
            "summary": summary,
            "history": history,
            "engine_version": self.engine_version,
            "policy": dataclasses.asdict(self.policy),
        }

    def encounter(self, event_id: str) -> dict | None:
        latest = self._latest(event_id)
        if latest is None:
            return None
        _, conversion = self._parsed(latest.sha256)
        conj = conversion.conjunction
        if conj.primary.covariance_rtn_m2 is None or conj.secondary.covariance_rtn_m2 is None:
            return None
        a = self._assess_sha(latest.sha256)
        hbr = a.get("hbr_m") or self.engine_config.default_radius_m
        if not hbr:
            return None
        try:
            plane = build_encounter_plane(conj, hbr, refine_tca=self.engine_config.refine_tca)
        except ValueError:
            return None
        if finite_eigenvalues(plane.cov_2d_m2) is None:
            return {"available": False, "reason": "projected covariance cannot be decomposed"}
        values, vectors = np.linalg.eigh(plane.cov_2d_m2)
        if np.any(values <= 0):
            return {"available": False, "reason": "projected covariance is not positive definite"}
        major = vectors[:, 1]
        curvature = curvilinear_check(conj, plane)
        return {
            "available": True,
            "model_applies": a["method"] == Method.FOSTER_ESTES_2D.value,
            "refusal_reason": a.get("refusal_reason"),
            "hbr_m": plane.hbr_m,
            "mu_m": plane.mu_m.tolist(),
            "cov_2d_m2": plane.cov_2d_m2.tolist(),
            "sigma_major_m": float(math.sqrt(values[1])),
            "sigma_minor_m": float(math.sqrt(values[0])),
            "major_axis_angle_rad": float(math.atan2(major[1], major[0])),
            "miss_distance_m": plane.relative.miss_distance_m,
            "relative_speed_m_s": plane.relative.speed_m_s,
            "tca_adjustment_s": plane.tca_adjustment_s,
            "curvilinear_ratio": curvature.ratio,
            "k_star": a["diagnostics"].get("k_star"),
        }

    def dilution_curve(self, event_id: str, samples: int = 161) -> dict | None:
        latest = self._latest(event_id)
        if latest is None:
            return None
        a = self._assess_sha(latest.sha256)
        _, conversion = self._parsed(latest.sha256)
        conj = conversion.conjunction
        hbr = a.get("hbr_m")
        if conj.primary.covariance_rtn_m2 is None or conj.secondary.covariance_rtn_m2 is None or not hbr:
            return None
        try:
            plane = build_encounter_plane(conj, hbr, refine_tca=self.engine_config.refine_tca)
        except ValueError:
            return None
        eigenvalues = finite_eigenvalues(plane.cov_2d_m2)
        if eigenvalues is None or eigenvalues[0] <= 0:
            return None
        from ..risk.integrate import maximize_pc_over_scale

        k_star, pc_max, _ = maximize_pc_over_scale(plane.cov_2d_m2, plane.mu_m, plane.hbr_m)
        lk_star = math.log10(k_star)
        lo = min(0.0, lk_star) - 2.0
        hi = max(0.0, lk_star) + 2.0
        grid = np.linspace(lo, hi, samples)
        return {
            "model_applies": a["method"] == Method.FOSTER_ESTES_2D.value,
            "log10_k": grid.tolist(),
            "pc": pc_curve(plane, grid).tolist(),
            "k_star": k_star,
            "pc_at_k1": plane.pc(1.0),
            "pc_max": pc_max,
            "diluted": k_star < 1.0,
        }

    def trajectory(self, event_id: str) -> dict | None:
        latest = self._latest(event_id)
        if latest is None:
            return None
        message, conversion = self._parsed(latest.sha256)
        arcs = encounter_arcs_ecef(conversion.conjunction, message.tca)
        return {"tca": message.tca.isoformat(), "note": "two-body arcs, visualization only", **arcs}

    def quarantined(self) -> list[dict]:
        return self.store.quarantined()


def _epoch(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso).timestamp())


def _consequence_rank(summary: dict) -> int:
    return ["ROUTINE", "WATCH", "SERIOUS", "CRITICAL"].index(summary["consequence"])


def _from_dict(d: dict) -> AssessedConjunction:
    return AssessedConjunction(
        method=Method(d["method"]),
        pc=d["pc"],
        pc_max=d["pc_max"],
        dilution_flag=d["dilution_flag"],
        dilution_margin=d["dilution_margin"],
        miss_distance_m=d["miss_distance_m"],
        relative_speed_m_s=d["relative_speed_m_s"],
        hbr_m=d["hbr_m"],
        inputs_hash=d["inputs_hash"],
        refusal_reason=None if d["refusal_reason"] is None else RefusalReason(d["refusal_reason"]),
        diagnostics=d["diagnostics"],
    )
