import type { PassUnit, PassWindow, PassesView, UnobservedGap } from "../api/types";

/**
 * Pass-module rules the console applies. The server computes every window
 * and gap; these only classify, check and explain what it sent.
 */

export type WindowKind = "eo" | "sar" | "unusable";

/** Legend text for each kind. Shape and text separate them, not colour alone. */
export const WINDOW_KIND_LABEL: Record<WindowKind, string> = {
  eo: "EO, unit lit: usable",
  sar: "SAR: usable",
  unusable: "EO at night: not usable",
};

/** A pass's identity across refetches: the imager and its rise. */
export function passKey(w: PassWindow): string {
  return `${w.norad_id}@${w.rise}`;
}

export function windowKind(w: PassWindow): WindowKind {
  if (!w.usable) return "unusable";
  return w.sensor === "SAR" ? "sar" : "eo";
}

/** Is the part of the window still ahead of `nowMs` at least the unit's
 *  reaction time? A window already open counts from now. */
export function meetsReactionTime(gap: UnobservedGap, reactionMin: number, nowMs: number): boolean {
  const from = Math.max(Date.parse(gap.start), nowMs);
  return Date.parse(gap.end) - from >= reactionMin * 60_000;
}

/** The look-ahead the reply covers, in hours. */
export function intervalHours(view: PassesView): number {
  return Math.round((Date.parse(view.end) - Date.parse(view.start)) / 3_600_000);
}

const SKIP_REASONS: Record<string, string> = {
  missing: "no element set for this NORAD id",
  name_mismatch: "the element set under this NORAD id is a different object",
};

export function skipReasonText(reason: string): string {
  return SKIP_REASONS[reason] ?? reason;
}

// ------------------------------------------------------------ unit form

/** The unit form's fields as typed. */
export type UnitDraft = Record<keyof PassUnit, string>;
export type UnitErrors = Partial<Record<keyof PassUnit, string>>;
type NumericField = Exclude<keyof PassUnit, "unit_id">;

interface NumericRule {
  field: NumericField;
  label: string;
  valid: (value: number) => boolean;
  rule: string;
}

// The ICD's 422 rules, checked before the request so the operator sees them
// at once. The server checks again; its answer is the one that counts.
const NUMERIC_RULES: NumericRule[] = [
  { field: "lat_deg", label: "Latitude", valid: (v) => v >= -90 && v <= 90, rule: "must be within -90 to 90 degrees" },
  { field: "lon_deg", label: "Longitude", valid: (v) => v >= -180 && v <= 180, rule: "must be within -180 to 180 degrees" },
  { field: "alt_m", label: "Altitude", valid: () => true, rule: "must be a number" },
  { field: "reaction_time_min", label: "Reaction time", valid: (v) => v > 0, rule: "must be a positive number of minutes" },
];

const parseNumber = (text: string): number => (text.trim() === "" ? NaN : Number(text));

export function validateUnit(draft: UnitDraft): { unit?: PassUnit; errors: UnitErrors } {
  const errors: UnitErrors = {};
  const unitId = draft.unit_id.trim();
  if (!unitId) errors.unit_id = "Unit id is required.";
  const values: Partial<Record<NumericField, number>> = {};
  for (const { field, label, valid, rule } of NUMERIC_RULES) {
    const value = parseNumber(draft[field]);
    if (!Number.isFinite(value)) errors[field] = `${label} must be a number.`;
    else if (!valid(value)) errors[field] = `${label} ${rule}.`;
    else values[field] = value;
  }
  if (Object.keys(errors).length > 0) return { errors };
  return { unit: { unit_id: unitId, ...(values as Record<NumericField, number>) }, errors };
}
