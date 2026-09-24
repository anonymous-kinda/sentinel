import type { Assessment } from "../api/types";
import { sci } from "../lib/format";

/**
 * The only component allowed to render a probability of collision.
 *
 * It takes the whole assessment, never a bare number, so a Pc cannot reach
 * the screen without the method that produced it, a refusal cannot be shown
 * as a zero, and a diluted Pc is always accompanied by its worst case.
 * This is the engine's Tier 6 output contract, enforced in the type system.
 */
export function PcValue({ assessment, size = "md" }: { assessment: Assessment; size?: "sm" | "md" | "lg" }) {
  if (assessment.method === "REFUSED" || assessment.pc === null) {
    return (
      <span className={`pc pc-${size} pc-refused`} title={assessment.refusal_reason ?? "refused"}>
        <span className="pc-label">Pc</span> refused
      </span>
    );
  }
  const diluted = assessment.dilution_flag && assessment.pc_max !== null;
  return (
    <span className={`pc pc-${size}${diluted ? " pc-diluted" : ""}`} title={`method ${assessment.method}`}>
      <span className="pc-label">Pc</span>
      <span className="pc-num">{sci(assessment.pc)}</span>
      {diluted && size !== "sm" && (
        <span className="pc-worst" title="Diluted: the Pc peak lies at a tighter covariance. This is the worst case over covariance scaling.">
          worst case {sci(assessment.pc_max as number)}
        </span>
      )}
    </span>
  );
}
