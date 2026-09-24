"""The classic apogee/perigee pre-filter (Hoots, Crawford and Roehrich, 1984).

Two objects whose radii never come within the threshold of each other
cannot come within the threshold either: |r1 - r2| >= | |r1| - |r2| |. So a
pair is dropped, before anything is propagated, when the higher perigee
sits above the lower apogee by more than the threshold.

The perigee and apogee come from mean elements. SGP4's short-period terms
carry the actual radius past them - by up to about 11 km on the snapshot
in fixtures/omm, measured in tests/screening/test_prefilter.py - so each
band is widened by PAD_KM on both sides before the comparison.

That measurement covers LEO (and one GEO object) over days. Highly
eccentric orbits and objects close to re-entry move further from their
mean-element band; re-measure the pad before screening such a catalogue.
"""

from __future__ import annotations

PAD_KM = 25.0

Band = tuple[float, float]  # (perigee, apogee) radius, km


def may_approach(band_a: Band, band_b: Band, threshold_km: float, pad_km: float = PAD_KM) -> bool:
    """False only when the two objects provably cannot come within threshold_km."""
    (perigee_a, apogee_a), (perigee_b, apogee_b) = band_a, band_b
    radial_gap_km = max(perigee_a, perigee_b) - min(apogee_a, apogee_b)
    return radial_gap_km <= threshold_km + 2.0 * pad_km
