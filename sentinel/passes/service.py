"""The pass module on a node: one unit, its pass windows and its gaps.

Everything here stays on the node (ADR-010). The unit lives in one private
file (unit.UnitFile). It is never a sync record, never logged, and never
published: the only bus message is `node.<id>.passes.updated`, which says
that the inputs moved and carries no unit and no coordinates. Node-scoped
subjects never cross a leaf link (ADR-009).

An answer is computed in three steps:
  1. pair the catalog with this node's element sets (match_catalog). An
     imager with no usable element set is skipped and reported, and then
     every gap is marked low confidence: a missing imager makes gaps look
     longer than they are;
  2. ask the provider for every window over [start, start + hours], with
     start this minute (floored, so the interval always contains now);
  3. the gaps between padded usable windows, and the first one at least
     the unit's reaction time long that is still to run after the true now.

Steps 1 and 2 cost about 0.4 s for 24 h, so their result is cached against
(unit, element-store version, start, hours). Step 3 is recomputed on every
call, because the cache's start is up to a minute behind now.
"""

from __future__ import annotations

import asyncio
import collections
import dataclasses
import datetime as dt
import json
import threading
from collections.abc import Callable, Mapping, Sequence

from ..bus import Bus, subjects
from ..clock import Clock
from ..obs import get_logger
from .element_store import ElementStore, element_epoch
from .elements import SECONDS_PER_DAY, ElementSet, Match, Skipped, match_catalog
from .gaps import Gap, next_unobserved, unobserved_gaps
from .geometry import STALE_AFTER_DAYS
from .model import Imager, PassProvider, PassWindow, Unit
from .providers.skyfield_local import SkyfieldProvider
from .unit import UnitFile, UnitRejected, validate_unit

log = get_logger(__name__)

MIN_HOURS = 1
MAX_HOURS = 72
CACHE_ENTRIES = 16
UPDATED = "passes.updated"
# An edge's first sync brings every element set in a burst, one record at a
# time. The console hears about the burst once, when it settles.
ELEMENTS_SETTLE_S = 1.0

ProviderFactory = Callable[[Mapping[int, ElementSet]], PassProvider]


class NoUnit(LookupError):
    """No unit is set on this node, so there is nothing to predict for."""


@dataclasses.dataclass(frozen=True)
class ElementAges:
    """The element sets that fed an answer, aged at its start."""

    oldest_age_days: float | None
    newest_age_days: float | None
    stale: int


@dataclasses.dataclass(frozen=True)
class PassReport:
    unit: Unit
    start: dt.datetime
    end: dt.datetime
    provider: str
    windows: tuple[PassWindow, ...]
    gaps: tuple[Gap, ...]
    next_unobserved: Gap | None
    imagers: tuple[Imager, ...]       # assessed
    skipped: tuple[Skipped, ...]      # catalogued, but not assessed
    elements: ElementAges


@dataclasses.dataclass(frozen=True)
class CatalogEntry:
    imager: Imager
    object_name: str              # the element set's OBJECT_NAME, as windows carry it
    element_epoch: dt.datetime
    element_age_days: float

    @property
    def stale(self) -> bool:
        return self.element_age_days > STALE_AFTER_DAYS


@dataclasses.dataclass(frozen=True)
class _Inputs:
    """What an answer is computed from, fixed for one element-store version."""

    version: int
    match: Match
    provider: PassProvider


class PassService:
    def __init__(
        self,
        store: ElementStore,
        catalog: Sequence[Imager],
        clock: Clock,
        units: UnitFile,
        bus: Bus,
        node_id: str,
        provider_factory: ProviderFactory = SkyfieldProvider,
        cache_entries: int = CACHE_ENTRIES,
        elements_settle_s: float = ELEMENTS_SETTLE_S,
    ):
        self._store = store
        self._catalog = list(catalog)
        self._clock = clock
        self._units = units
        self._bus = bus
        self._node_id = node_id
        self._provider_factory = provider_factory
        self._cache_entries = cache_entries
        self._cache: collections.OrderedDict[tuple, PassReport] = collections.OrderedDict()
        self._inputs: _Inputs | None = None
        self._lock = threading.Lock()
        self._elements_settle_s = elements_settle_s
        self._elements_event: asyncio.Task | None = None
        self._unit = self._load_unit()

    # ------------------------------------------------------------------ unit
    @property
    def unit(self) -> Unit | None:
        return self._unit

    async def set_unit(self, unit: Unit) -> Unit:
        validate_unit(unit)
        self._units.save(unit)
        self._unit = unit
        log.info("Unit set")
        await self._publish("unit_set")
        return unit

    async def clear_unit(self) -> None:
        self._units.clear()
        self._unit = None
        log.info("Unit cleared")
        await self._publish("unit_cleared")

    async def elements_changed(self) -> None:
        """A synced element set changed the store. The console is told once
        the burst settles: at most one event per settle interval, and a
        change after an event is sent always schedules another."""
        if self._elements_event is None:
            self._elements_event = asyncio.get_running_loop().create_task(self._publish_elements_when_settled())

    async def _publish_elements_when_settled(self) -> None:
        await asyncio.sleep(self._elements_settle_s)
        self._elements_event = None
        await self._publish("elements")

    def _load_unit(self) -> Unit | None:
        try:
            return self._units.load()
        except UnitRejected as exc:
            log.error("Unit file unreadable", field=exc.field, detail=exc.detail)
            return None

    async def _publish(self, reason: str) -> None:
        payload = {"reason": reason, "elements_version": self._store.version}
        await self._bus.publish(
            subjects.local(self._node_id, UPDATED), json.dumps(payload).encode(), {"Sentinel-Kind": UPDATED}
        )

    # ---------------------------------------------------------------- passes
    def passes(self, hours: float) -> PassReport:
        if not MIN_HOURS <= hours <= MAX_HOURS:
            raise ValueError(f"hours must be within [{MIN_HOURS}, {MAX_HOURS}]")
        unit = self._unit
        if unit is None:
            raise NoUnit()
        now = self._clock.now()
        report = self._windows_and_gaps(unit, now.replace(second=0, microsecond=0), hours)
        reaction = dt.timedelta(minutes=unit.reaction_time_min)
        return dataclasses.replace(report, next_unobserved=next_unobserved(report.gaps, now, reaction))

    def _windows_and_gaps(self, unit: Unit, start: dt.datetime, hours: float) -> PassReport:
        with self._lock:
            inputs = self._current_inputs()
            key = (unit, inputs.version, start, hours)
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            report = _compute(unit, start, start + dt.timedelta(hours=hours), inputs)
            self._cache[key] = report
            if len(self._cache) > self._cache_entries:
                self._cache.popitem(last=False)
            return report

    def _current_inputs(self) -> _Inputs:
        version = self._store.version
        if self._inputs is None or self._inputs.version != version:
            elements = self._store.latest()
            self._inputs = _Inputs(version, match_catalog(self._catalog, elements), self._provider_factory(elements))
        return self._inputs

    # --------------------------------------------------------------- catalog
    def catalog(self) -> tuple[list[CatalogEntry], list[Skipped]]:
        with self._lock:
            match = self._current_inputs().match
        now = self._clock.now()
        entries = [_catalog_entry(imager, match.element_sets[imager.norad_id], now) for imager in match.imagers]
        return entries, list(match.skipped)


def _compute(unit: Unit, start: dt.datetime, end: dt.datetime, inputs: _Inputs) -> PassReport:
    match = inputs.match
    windows = inputs.provider.windows(unit, match.imagers, start, end)
    gaps = unobserved_gaps(windows, start, end)
    if match.skipped:
        gaps = [dataclasses.replace(gap, low_confidence=True) for gap in gaps]
    log.debug("Passes computed", windows=len(windows), gaps=len(gaps), skipped=len(match.skipped))
    return PassReport(
        unit=unit,
        start=start,
        end=end,
        provider=inputs.provider.name,
        windows=tuple(windows),
        gaps=tuple(gaps),
        next_unobserved=None,
        imagers=tuple(match.imagers),
        skipped=tuple(match.skipped),
        elements=_ages(match.element_sets.values(), start),
    )


def _age_days(element_set: ElementSet, when: dt.datetime) -> float:
    return (when - element_epoch(dict(element_set))).total_seconds() / SECONDS_PER_DAY


def _ages(element_sets, when: dt.datetime) -> ElementAges:
    ages = [_age_days(element_set, when) for element_set in element_sets]
    if not ages:
        return ElementAges(None, None, 0)
    return ElementAges(max(ages), min(ages), sum(age > STALE_AFTER_DAYS for age in ages))


def _catalog_entry(imager: Imager, element_set: ElementSet, now: dt.datetime) -> CatalogEntry:
    return CatalogEntry(
        imager, element_set["OBJECT_NAME"], element_epoch(dict(element_set)), _age_days(element_set, now)
    )
