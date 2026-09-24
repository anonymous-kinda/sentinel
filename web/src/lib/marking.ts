/**
 * The level a classification marking starts with, which sets the banner's
 * colour (green U, purple CUI, blue C, red S, orange TS). The banner text is
 * the marking itself; the colour only repeats it. A marking this cannot
 * read, or none yet, is "unknown" and never drawn in UNCLASSIFIED green.
 */
export type MarkingLevel = "unclassified" | "cui" | "confidential" | "secret" | "top-secret" | "unknown";

// Longest first: TOP SECRET must not read as SECRET.
const LEVELS: [prefix: string, level: MarkingLevel][] = [
  ["TOP SECRET", "top-secret"],
  ["SECRET", "secret"],
  ["CONFIDENTIAL", "confidential"],
  ["CUI", "cui"],
  ["UNCLASSIFIED", "unclassified"],
];

export function markingLevel(marking: string | null): MarkingLevel {
  const text = (marking ?? "").trim().toUpperCase();
  return LEVELS.find(([prefix]) => text.startsWith(prefix))?.[1] ?? "unknown";
}
