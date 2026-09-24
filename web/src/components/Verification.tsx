import type { EventSummary } from "../api/types";

const TEXT: Record<string, { label: string; title: string; cls: string }> = {
  HUB_ASSERTED: {
    label: "HUB-ASSERTED",
    title: "Known from the hub's summary only. No covariance has reached this node, so it cannot have recomputed the Pc.",
    cls: "ver-asserted",
  },
  UPDATING: { label: "UPDATING", title: "The hub holds a newer CDM that is still in the sync queue.", cls: "ver-updating" },
  VERIFIED: {
    label: "✓ VERIFIED",
    title: "The full CDM arrived, was re-assessed on this node, and matches what the hub asserted.",
    cls: "ver-verified",
  },
  MISMATCH: {
    label: "MISMATCH",
    title: "Same CDM, different result on this node than the hub asserted. Investigate before acting.",
    cls: "ver-mismatch",
  },
};

export function VerificationChip({ v }: { v: EventSummary["verification"] }) {
  if (!v || v === "LOCAL") return null;
  const t = TEXT[v];
  return (
    <span className={`chip ${t.cls}`} title={t.title}>
      {t.label}
    </span>
  );
}
