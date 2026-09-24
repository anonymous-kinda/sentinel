import type { Assessment } from "../api/types";
import { sci } from "../lib/format";

/** The engine returned a Pc: not refused, and a number. */
const computed = (a: Assessment): a is Assessment & { pc: number } => a.method !== "REFUSED" && a.pc !== null;

/** The worst case over covariance scaling, when the Pc is diluted. */
const worstCase = (a: Assessment): number | null => (a.dilution_flag && a.pc_max !== null ? a.pc_max : null);

/**
 * The only component allowed to render a probability of collision.
 *
 * It takes the whole assessment, never a bare number, so a Pc cannot reach
 * the screen without the method that produced it, a refusal cannot be shown
 * as a zero, and a diluted Pc is always accompanied by its worst case.
 * This is the engine's Tier 6 output contract, enforced in the type system.
 */
export function PcValue({ assessment, size = "md" }: { assessment: Assessment; size?: "sm" | "md" | "lg" }) {
  if (!computed(assessment)) {
    return (
      <span className={`pc pc-${size} pc-refused`} title={assessment.refusal_reason ?? "refused"}>
        <span className="pc-label">Pc</span> refused
      </span>
    );
  }
  const worst = worstCase(assessment);
  return (
    <span className={`pc pc-${size}${worst !== null ? " pc-diluted" : ""}`} title={`method ${assessment.method}`}>
      <span className="pc-label">Pc</span>
      <span className="pc-num">{sci(assessment.pc)}</span>
      {worst !== null && (
        <span className="pc-worst" title="Diluted: the Pc peak lies at a tighter covariance. This is the worst case over covariance scaling.">
          {size === "sm" ? "worst" : "worst case"} {sci(worst)}
        </span>
      )}
    </span>
  );
}

/** The same contract as plain text, for a place that cannot hold markup
 *  such as an SVG <title>: the method, a refusal as "refused", and a
 *  diluted Pc's worst case. */
export function pcText(assessment: Assessment): string {
  if (!computed(assessment)) return `Pc refused (${assessment.refusal_reason ?? "no reason given"})`;
  const worst = worstCase(assessment);
  return `Pc ${sci(assessment.pc)} by ${assessment.method}${worst !== null ? `, diluted: worst case ${sci(worst)}` : ""}`;
}
