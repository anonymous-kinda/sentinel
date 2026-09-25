/// <reference types="vite/client" />
import indexHtml from "../../../index.html?raw";

/**
 * The console's own source, as text, for checks that read code rather than
 * run it: the Pc contract and the Content-Security-Policy. Tests are left
 * out; they hold hostile strings on purpose.
 */
const raw = import.meta.glob(["../../**/*.{ts,tsx,css}", "!../../__tests__/**"], {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** Keyed by path from web/, e.g. "src/components/PcValue.tsx". */
export const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(raw).map(([path, text]) => [path.replace(/^(\.\.\/)+/, "src/"), text]),
);

export const INDEX_HTML: string = indexHtml;

export interface Hit {
  file: string;
  line: number;
  text: string;
}

/** Every match of `pattern` (global) in `text`, with its line number. */
export function findAll(file: string, text: string, pattern: RegExp, keep: (match: RegExpExecArray) => boolean = () => true): Hit[] {
  const hits: Hit[] = [];
  for (const match of text.matchAll(pattern)) {
    if (!keep(match)) continue;
    const line = text.slice(0, match.index).split("\n").length;
    hits.push({ file, line, text: match[0] });
  }
  return hits;
}
