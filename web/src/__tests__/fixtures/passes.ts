import type { PassCatalog, PassUnit, PassesView } from "../../api/types";

// Payloads shaped exactly like the examples in docs/icd/passes-api.md, with
// the "..." times filled in. The numbers are hand-written test data, not
// output of the pass engine. Pads follow the ICD's 60 s + 30 s per day of
// element age; gaps are the interval minus the padded *usable* windows.

/** The node clock in these tests: 11:10Z, after the first gap has become
 *  too short for the unit's reaction time. */
export const NOW_ISO = "2026-09-24T11:10:00Z";
export const NOW_MS = Date.parse(NOW_ISO);

export const unit: PassUnit = {
  unit_id: "EX-UNIT-1",
  lat_deg: 35.26,
  lon_deg: -116.68,
  alt_m: 700.0,
  reaction_time_min: 30.0,
};

export const nightEO = {
  norad_id: 40115,
  name: "WORLDVIEW-3 (WV-3)",
  sensor: "EO",
  rise: "2026-09-24T07:30:00+00:00",
  culmination: "2026-09-24T07:34:00+00:00",
  set: "2026-09-24T07:38:00+00:00",
  padded_start: "2026-09-24T07:28:45+00:00",
  padded_end: "2026-09-24T07:39:15+00:00",
  pad_s: 75.0,
  max_elevation_deg: 48.7,
  mask_elevation_deg: 40.3,
  element_age_days: 0.5,
  stale: false,
  sunlit: false,
  usable: false,
} as const;

export const sar = {
  norad_id: 31698,
  name: "TERRASAR-X",
  sensor: "SAR",
  rise: "2026-09-24T11:20:00+00:00",
  culmination: "2026-09-24T11:24:30+00:00",
  set: "2026-09-24T11:29:00+00:00",
  padded_start: "2026-09-24T11:18:54+00:00",
  padded_end: "2026-09-24T11:30:06+00:00",
  pad_s: 66.0,
  max_elevation_deg: 52.0,
  mask_elevation_deg: 27.6,
  element_age_days: 0.2,
  stale: false,
  sunlit: null,
  usable: true,
} as const;

export const dayEO = {
  norad_id: 40115,
  name: "WORLDVIEW-3 (WV-3)",
  sensor: "EO",
  rise: "2026-09-24T18:02:00+00:00",
  culmination: "2026-09-24T18:06:00+00:00",
  set: "2026-09-24T18:10:00+00:00",
  padded_start: "2026-09-24T18:00:45+00:00",
  padded_end: "2026-09-24T18:11:15+00:00",
  pad_s: 75.0,
  max_elevation_deg: 61.2,
  mask_elevation_deg: 40.3,
  element_age_days: 0.5,
  stale: false,
  sunlit: true,
  usable: true,
} as const;

export const staleEO = {
  norad_id: 40697,
  name: "SENTINEL-2A",
  sensor: "EO",
  rise: "2026-09-24T21:40:00+00:00",
  culmination: "2026-09-24T21:44:00+00:00",
  set: "2026-09-24T21:48:00+00:00",
  padded_start: "2026-09-24T21:36:54+00:00",
  padded_end: "2026-09-24T21:51:06+00:00",
  pad_s: 186.0,
  max_elevation_deg: 83.1,
  mask_elevation_deg: 79.0,
  element_age_days: 4.2,
  stale: true,
  sunlit: true,
  usable: true,
} as const;

export const GAP_LABEL = "not observed by catalogued imagers";

export const gaps = [
  { start: "2026-09-24T06:00:00+00:00", end: "2026-09-24T11:18:54+00:00", duration_s: 19134.0, low_confidence: false },
  { start: "2026-09-24T11:30:06+00:00", end: "2026-09-24T18:00:45+00:00", duration_s: 23439.0, low_confidence: false },
  { start: "2026-09-24T18:11:15+00:00", end: "2026-09-24T21:36:54+00:00", duration_s: 12339.0, low_confidence: true },
  { start: "2026-09-24T21:51:06+00:00", end: "2026-09-25T06:00:00+00:00", duration_s: 29334.0, low_confidence: true },
];

export const passes: PassesView = {
  unit,
  start: "2026-09-24T06:00:00+00:00",
  end: "2026-09-25T06:00:00+00:00",
  provider: "skyfield-local",
  label: GAP_LABEL,
  windows: [nightEO, sar, dayEO, staleEO],
  gaps,
  next_unobserved: gaps[1],
  catalog: { imagers: 38, skipped: [] },
  elements: { oldest_age_days: 4.2, newest_age_days: 0.2, stale: 1 },
};

export const skipped = { norad_id: 0, name: "EX-IMAGER", reason: "missing" };

export const catalog: PassCatalog = {
  imagers: [
    {
      norad_id: 40115,
      name: "WORLDVIEW-3 (WV-3)",
      sensor: "EO",
      max_off_nadir_deg: 45.0,
      gsd_m: 0.31,
      basis: "Planning assumption: vendor collection at high off-nadir. Source: vendor datasheet.",
      element_epoch: "2026-09-23T23:10:00+00:00",
      element_age_days: 0.5,
      stale: false,
    },
    {
      norad_id: 31698,
      name: "TERRASAR-X",
      sensor: "SAR",
      max_off_nadir_deg: 60.0,
      gsd_m: 1.0,
      basis: "Planning assumption: accessible incidence 15-60 deg, maximum read as off-nadir (errs wide).",
      element_epoch: "2026-09-24T06:22:00+00:00",
      element_age_days: 0.2,
      stale: false,
    },
    {
      norad_id: 40697,
      name: "SENTINEL-2A",
      sensor: "EO",
      max_off_nadir_deg: 10.3,
      gsd_m: 10.0,
      basis: "Planning assumption: nadir-pointing MSI, half its 20.6 deg field of view.",
      element_epoch: "2026-09-20T06:22:00+00:00",
      element_age_days: 4.2,
      stale: true,
    },
  ],
  skipped: [skipped],
};
