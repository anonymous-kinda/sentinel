"""Exercise scenario: synthetic CDM sequences for demonstration.

Every message is labelled at the source - ORIGINATOR = SENTINEL-EXERCISE,
an EXERCISE comment line, and fictional object names in the 99xxx range -
and the service classifies anything from that originator as EXERCISE data
regardless of how it arrived. Nothing here pretends to be a real event.

Each scripted event is a sequence of CDM updates, the way operators
actually receive them. Updates are timestamped relative to an epoch (the
moment the scenario starts); those dated after the epoch are released as
the clock reaches them, so the console changes while you watch.

Scripted events and what each demonstrates:

  EX-DIL   covariance inflates as tracking degrades; Pc rises, peaks and
           falls while the dilution flag lights - the headline pathology
  EX-RED   RED from its first CDM: over four updates the covariance
           tightens and the miss closes from 260 m to 200 m; Pc rises while
           the event is diluted, and eases on the last update, the first
           that is not; TCA 19 h after the epoch, so its maneuver commit
           point is 11 h after it (tests/conjunction/test_exercise_scenario.py)
  EX-AMB   steady AMBER, not diluted
  EX-GRN   routine GREEN
  EX-GEO   geostationary co-location at 0.3 m/s - refused, low velocity
  EX-NOCOV secondary catalogued from element sets only - refused, no covariance
  EX-BAN   300 km along-track sigma - refused, curvilinear uncertainty
  EX-NPD   non-positive-definite covariance from upstream - refused
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math

import numpy as np

from ..cdm import emit
from ..cdm.model import CdmMessage, CdmSection, Comment, KvnField
from ..cdm.timefmt import format_ccsds_time
from ..risk.frames import rtn_to_eci_matrix

MU_KM3_S2 = 398600.4418
R_EARTH_KM = 6378.137
HBR_M = 20.0


@dataclasses.dataclass(frozen=True)
class ObjectSpec:
    designator: str
    name: str
    object_type: str            # PAYLOAD | DEBRIS | ROCKET BODY
    maneuverable: bool


@dataclasses.dataclass(frozen=True)
class Update:
    """One CDM in an event's sequence."""

    offset_h: float                                  # creation time relative to epoch
    sigma_rtn_primary_m: tuple[float, float, float] | None
    sigma_rtn_secondary_m: tuple[float, float, float] | None
    miss_m: float
    non_pd: bool = False


@dataclasses.dataclass(frozen=True)
class EventScript:
    key: str
    primary: ObjectSpec
    secondary: ObjectSpec
    tca_offset_h: float
    altitude_km: float
    inclination_deg: float
    raan_deg: float
    arg_latitude_deg: float
    crossing_deg: float                  # angle between the two velocity vectors
    miss_clock_deg: float                # direction of the miss in the encounter plane
    updates: tuple[Update, ...]
    geo_relative_speed_m_s: float | None = None


EXSAT = ObjectSpec("99001", "EXSAT-1 (EXERCISE)", "PAYLOAD", True)
EXGEO = ObjectSpec("99007", "EXGEO-7 (EXERCISE)", "PAYLOAD", True)


def _deb(n: int) -> ObjectSpec:
    return ObjectSpec(f"99{n:03d}", f"EX-DEB {n} (EXERCISE)", "DEBRIS", False)


SCENARIO: tuple[EventScript, ...] = (
    EventScript(
        "EX-DIL", EXSAT, _deb(412), tca_offset_h=30.0, altitude_km=550.0,
        inclination_deg=53.0, raan_deg=40.0, arg_latitude_deg=75.0,
        crossing_deg=160.0, miss_clock_deg=35.0,
        updates=(
            Update(-20.0, (40, 250, 40), (180, 380, 170), 800.0),
            Update(-12.0, (40, 250, 40), (300, 760, 290), 800.0),
            Update(-4.0, (40, 250, 40), (520, 1500, 500), 800.0),
            Update(0.02, (40, 250, 40), (1000, 3000, 950), 800.0),
            Update(0.06, (40, 250, 40), (2200, 6500, 2100), 800.0),
        ),
    ),
    EventScript(
        "EX-RED", EXSAT, _deb(118), tca_offset_h=19.0, altitude_km=550.0,
        inclination_deg=53.0, raan_deg=40.0, arg_latitude_deg=200.0,
        crossing_deg=95.0, miss_clock_deg=110.0,
        updates=(
            Update(-26.0, (40, 300, 40), (260, 1200, 250), 260.0),
            Update(-15.0, (30, 200, 28), (140, 650, 130), 230.0),
            Update(-6.0, (20, 120, 18), (70, 320, 65), 210.0),
            Update(0.04, (12, 70, 11), (35, 160, 32), 200.0),
        ),
    ),
    EventScript(
        "EX-AMB", EXSAT, _deb(733), tca_offset_h=44.0, altitude_km=550.0,
        inclination_deg=53.0, raan_deg=40.0, arg_latitude_deg=310.0,
        crossing_deg=40.0, miss_clock_deg=70.0,
        updates=(
            Update(-16.0, (50, 300, 45), (140, 700, 130), 900.0),
            Update(-3.0, (45, 260, 40), (120, 600, 110), 850.0),
        ),
    ),
    EventScript(
        "EX-GRN", EXSAT, _deb(905), tca_offset_h=66.0, altitude_km=550.0,
        inclination_deg=53.0, raan_deg=40.0, arg_latitude_deg=15.0,
        crossing_deg=170.0, miss_clock_deg=10.0,
        updates=(Update(-8.0, (50, 300, 45), (300, 1500, 280), 2200.0),),
    ),
    EventScript(
        "EX-GEO", EXGEO, _deb(207), tca_offset_h=52.0, altitude_km=35786.0,
        inclination_deg=0.05, raan_deg=0.0, arg_latitude_deg=120.0,
        crossing_deg=0.0, miss_clock_deg=80.0,
        updates=(Update(-10.0, (40, 300, 40), (200, 1500, 200), 900.0),),
        geo_relative_speed_m_s=0.3,
    ),
    EventScript(
        "EX-NOCOV", EXSAT, _deb(560), tca_offset_h=11.0, altitude_km=550.0,
        inclination_deg=53.0, raan_deg=40.0, arg_latitude_deg=260.0,
        crossing_deg=120.0, miss_clock_deg=200.0,
        updates=(Update(-5.0, (50, 300, 45), None, 260.0),),
    ),
    EventScript(
        "EX-BAN", EXSAT, _deb(881), tca_offset_h=58.0, altitude_km=550.0,
        inclination_deg=53.0, raan_deg=40.0, arg_latitude_deg=140.0,
        crossing_deg=150.0, miss_clock_deg=300.0,
        updates=(Update(-7.0, (50, 300, 45), (900, 300_000, 800), 1500.0),),
    ),
    EventScript(
        "EX-NPD", EXSAT, _deb(349), tca_offset_h=36.0, altitude_km=550.0,
        inclination_deg=53.0, raan_deg=40.0, arg_latitude_deg=240.0,
        crossing_deg=75.0, miss_clock_deg=150.0,
        updates=(Update(-9.0, (50, 300, 45), (150, 700, 140), 600.0, non_pd=True),),
    ),
)


def _rotation(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(angle_rad) * k + (1 - math.cos(angle_rad)) * (k @ k)


def _geometry(script: EventScript, miss_m: float):
    """States (km, km/s) of both objects at TCA with the requested miss."""
    radius = R_EARTH_KM + script.altitude_km
    speed = math.sqrt(MU_KM3_S2 / radius)
    inc, raan, u = map(math.radians, (script.inclination_deg, script.raan_deg, script.arg_latitude_deg))
    # Circular orbit: position and velocity from argument of latitude.
    r_pqw = np.array([math.cos(u), math.sin(u), 0.0]) * radius
    v_pqw = np.array([-math.sin(u), math.cos(u), 0.0]) * speed
    rot = _rotation(np.array([0, 0, 1.0]), raan) @ _rotation(np.array([1.0, 0, 0]), inc)
    r1 = rot @ r_pqw
    v1 = rot @ v_pqw

    r_hat = r1 / np.linalg.norm(r1)
    if script.geo_relative_speed_m_s is not None:
        # Co-located GEO objects: nearly identical velocity, tiny difference
        # along the orbit normal.
        n_hat = np.cross(r1, v1) / np.linalg.norm(np.cross(r1, v1))
        v2 = v1 + n_hat * (script.geo_relative_speed_m_s / 1000.0)
    else:
        v2 = _rotation(r_hat, math.radians(script.crossing_deg)) @ v1

    dv = v2 - v1
    z_hat = dv / np.linalg.norm(dv)
    y_plane = np.cross(z_hat, r_hat)
    y_plane /= np.linalg.norm(y_plane)
    x_plane = np.cross(y_plane, z_hat)
    clock = math.radians(script.miss_clock_deg)
    miss_dir = math.cos(clock) * x_plane + math.sin(clock) * y_plane
    r2 = r1 + miss_dir * (miss_m / 1000.0)
    return r1, v1, r2, v2


def _cov_block(sigma_rtn_m: tuple[float, float, float] | None, non_pd: bool) -> list[KvnField]:
    names = ["CR_R", "CT_R", "CT_T", "CN_R", "CN_T", "CN_N"]
    if sigma_rtn_m is None:
        return [KvnField(n, "NaN", "m**2") for n in names]
    sr, st, sn = sigma_rtn_m
    cov = np.diag([sr * sr, st * st, sn * sn])
    cov[0, 1] = cov[1, 0] = -0.3 * sr * st  # radial/along-track correlation, typical of OD
    if non_pd:
        cov[0, 1] = cov[1, 0] = 1.4 * sr * st  # |rho| > 1: not a covariance
    values = [cov[0, 0], cov[1, 0], cov[1, 1], cov[2, 0], cov[2, 1], cov[2, 2]]
    fields = [KvnField(n, f"{v:.9e}", "m**2") for n, v in zip(names, values)]
    # Velocity terms: small and uncorrelated, present because real CDMs carry them.
    vel = [
        ("CRDOT_R", 0.0, "m**2/s"), ("CRDOT_T", 0.0, "m**2/s"), ("CRDOT_N", 0.0, "m**2/s"),
        ("CRDOT_RDOT", 1e-4, "m**2/s**2"), ("CTDOT_R", 0.0, "m**2/s"), ("CTDOT_T", 0.0, "m**2/s"),
        ("CTDOT_N", 0.0, "m**2/s"), ("CTDOT_RDOT", 0.0, "m**2/s**2"), ("CTDOT_TDOT", 1e-4, "m**2/s**2"),
        ("CNDOT_R", 0.0, "m**2/s"), ("CNDOT_T", 0.0, "m**2/s"), ("CNDOT_N", 0.0, "m**2/s"),
        ("CNDOT_RDOT", 0.0, "m**2/s**2"), ("CNDOT_TDOT", 0.0, "m**2/s**2"), ("CNDOT_NDOT", 1e-4, "m**2/s**2"),
    ]
    return fields + [KvnField(n, f"{v:.9e}", u) for n, v, u in vel]


def _object(index: int, spec: ObjectSpec, r_km, v_km_s, sigma, non_pd) -> CdmSection:
    entries = [
        KvnField("OBJECT", f"OBJECT{index}"),
        KvnField("OBJECT_DESIGNATOR", spec.designator),
        KvnField("CATALOG_NAME", "SATCAT"),
        KvnField("OBJECT_NAME", spec.name),
        KvnField("INTERNATIONAL_DESIGNATOR", "EXERCISE"),
        KvnField("OBJECT_TYPE", spec.object_type),
        KvnField("EPHEMERIS_NAME", "NONE"),
        KvnField("COVARIANCE_METHOD", "CALCULATED" if sigma is not None else "DEFAULT"),
        KvnField("MANEUVERABLE", "YES" if spec.maneuverable else "NO"),
        KvnField("REF_FRAME", "EME2000"),
    ]
    if sigma is None:
        entries.append(Comment("covariance unavailable: secondary catalogued from element sets only"))
    for key, value in zip(("X", "Y", "Z"), r_km):
        entries.append(KvnField(key, f"{value:.6f}", "km"))
    for key, value in zip(("X_DOT", "Y_DOT", "Z_DOT"), v_km_s):
        entries.append(KvnField(key, f"{value:.9f}", "km/s"))
    entries.extend(_cov_block(sigma, non_pd))
    return CdmSection(tuple(entries))


def build_message(script: EventScript, index: int, update: Update, epoch: dt.datetime) -> CdmMessage:
    tca = epoch + dt.timedelta(hours=script.tca_offset_h)
    tca = tca.replace(microsecond=(tca.microsecond // 1000) * 1000)
    created = epoch + dt.timedelta(hours=update.offset_h)
    r1, v1, r2, v2 = _geometry(script, update.miss_m)

    m = rtn_to_eci_matrix(r1, v1)
    dr_rtn = m.T @ ((r2 - r1) * 1000.0)
    dv_rtn = m.T @ ((v2 - v1) * 1000.0)

    preamble = CdmSection(
        (
            KvnField("CCSDS_CDM_VERS", "1.0"),
            KvnField("CREATION_DATE", format_ccsds_time(created)),
            KvnField("ORIGINATOR", "SENTINEL-EXERCISE"),
            KvnField("MESSAGE_FOR", script.primary.name),
            KvnField("MESSAGE_ID", f"{script.key}-{index:02d}-{created:%Y%m%dT%H%M%S}"),
            Comment("EXERCISE EXERCISE EXERCISE - synthetic data, not a real conjunction"),
            KvnField("TCA", format_ccsds_time(tca)),
            KvnField("MISS_DISTANCE", f"{np.linalg.norm(dr_rtn):.3f}", "m"),
            KvnField("RELATIVE_SPEED", f"{np.linalg.norm(dv_rtn):.3f}", "m/s"),
            KvnField("RELATIVE_POSITION_R", f"{dr_rtn[0]:.3f}", "m"),
            KvnField("RELATIVE_POSITION_T", f"{dr_rtn[1]:.3f}", "m"),
            KvnField("RELATIVE_POSITION_N", f"{dr_rtn[2]:.3f}", "m"),
            KvnField("RELATIVE_VELOCITY_R", f"{dv_rtn[0]:.3f}", "m/s"),
            KvnField("RELATIVE_VELOCITY_T", f"{dv_rtn[1]:.3f}", "m/s"),
            KvnField("RELATIVE_VELOCITY_N", f"{dv_rtn[2]:.3f}", "m/s"),
            Comment(f"HBR = {HBR_M:g} [m]"),
        )
    )
    return CdmMessage(
        preamble=preamble,
        objects=(
            _object(1, script.primary, r1, v1, update.sigma_rtn_primary_m, False),
            _object(2, script.secondary, r2, v2, update.sigma_rtn_secondary_m, update.non_pd),
        ),
    )


@dataclasses.dataclass(frozen=True)
class ScheduledCdm:
    release_at: dt.datetime
    filename: str
    kvn: str


def generate(epoch: dt.datetime) -> list[ScheduledCdm]:
    """The whole scenario, ordered by release time."""
    out = []
    for script in SCENARIO:
        for i, update in enumerate(script.updates, start=1):
            message = build_message(script, i, update, epoch)
            created = epoch + dt.timedelta(hours=update.offset_h)
            out.append(ScheduledCdm(created, f"{message.message_id}.cdm", emit(message)))
    return sorted(out, key=lambda s: s.release_at)
