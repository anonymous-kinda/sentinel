const SUPERSCRIPT: Record<string, string> = {
  "-": "⁻", "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
};

/** 3.6×10⁻⁵ - how a probability reads on a console. */
export function sci(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return String(value);
  if (value === 0) return "0";
  const [mantissa, exponent] = value.toExponential(digits - 1).split("e");
  const exp = String(Number(exponent));
  return `${mantissa}×10${exp.split("").map((c) => SUPERSCRIPT[c] ?? c).join("")}`;
}

/** 3.6e-5 - compact form for tables and axes. */
export function sciPlain(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return String(value);
  if (value === 0) return "0";
  const [mantissa, exponent] = value.toExponential(digits - 1).split("e");
  return `${mantissa}e${Number(exponent)}`;
}

export function metres(value: number): string {
  if (Math.abs(value) >= 10_000) return `${(value / 1000).toFixed(1)} km`;
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(2)} km`;
  return `${value.toFixed(value < 10 ? 2 : 0)} m`;
}

export function speed(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(2)} km/s`;
  return `${value.toFixed(value < 10 ? 2 : 0)} m/s`;
}

/** T-10h 32m, or +3h 05m past. */
export function countdown(seconds: number): string {
  const sign = seconds < 0 ? "+" : "T−";
  let s = Math.abs(Math.round(seconds));
  const d = Math.floor(s / 86400);
  s -= d * 86400;
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  if (d > 0) return `${sign}${d}d ${String(h).padStart(2, "0")}h`;
  if (h > 0) return `${sign}${h}h ${String(m).padStart(2, "0")}m`;
  return `${sign}${m}m ${String(s - m * 60).padStart(2, "0")}s`;
}

/** 1h 30m - a length of time, rounded to the minute, with no sign. */
export function duration(seconds: number): string {
  const minutes = Math.round(Math.abs(seconds) / 60);
  const h = Math.floor(minutes / 60);
  const m = minutes - h * 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** Military date-time group: 241907Z SEP 26. */
export function dtg(iso: string): string {
  const d = new Date(iso);
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${dd}${hh}${mm}Z ${MONTHS[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`;
}

export function utc(iso: string): string {
  return new Date(iso).toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

export function shortHash(hash: string, n = 12): string {
  return hash.slice(0, n);
}

export const REFUSAL_TEXT: Record<string, string> = {
  NO_COVARIANCE: "No covariance - geometry only. A Pc cannot be computed from element sets.",
  NO_HBR: "No hard-body radius available and no default policy configured.",
  INVALID_COVARIANCE: "Covariance is not positive definite. Refused, not repaired.",
  ILL_CONDITIONED_COVARIANCE: "Covariance too ill-conditioned for a meaningful projection.",
  LOW_RELATIVE_VELOCITY: "Relative speed too low for the straight-line encounter model. Needs 3D assessment.",
  TCA_INCONSISTENT: "States are not at closest approach. The message is internally inconsistent.",
  CURVILINEAR_UNCERTAINTY: "Along-track uncertainty bends too far along the orbit for a flat 2D Gaussian. Needs 3D assessment.",
  UNRESOLVED_INTEGRAL: "Uncertainty too small against the hard-body radius to integrate in double precision. Refused, not guessed.",
};
