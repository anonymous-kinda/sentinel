import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EventDetail } from "../components/EventDetail";
import { HistorySpark } from "../components/HistorySpark";
import { mockApi, ok } from "./fixtures/api";
import { detail, diluted, summary } from "./fixtures/events";
import { SOURCES, findAll, type Hit } from "./fixtures/sources";

/**
 * The repo rule: a Pc renders only through PcValue, which takes the whole
 * assessment, so a Pc never reaches the screen without its method, a
 * refusal never shows as a zero and a diluted Pc always shows its worst
 * case. This scan finds a Pc formatted anywhere else. It is conservative:
 * it looks for the console's number formatters applied to something named
 * like a Pc, and exists to catch a regression, not to prove the rule.
 */

const FORMATTER = /\b(?:sci|sciPlain)\(((?:[^()]|\([^()]*\))*)\)|([\w$.?]+)\.(?:toExponential|toPrecision|toFixed)\(/g;
const NAMES_A_PC = /(?:^|[^A-Za-z])pc(?:[^a-z]|$)|_pc|pc_/;

/** PcValue owns the rendering and format.ts the formatting. */
const OWNERS = new Set(["src/components/PcValue.tsx", "src/lib/format.ts"]);

/** Places that show a Pc that is not a Sentinel assessment of an event. */
const ALLOWED: Record<string, { count: number; why: string }> = {
  "src/components/DilutionCurve.tsx": {
    count: 3,
    why: "the Pc(k) sensitivity curve: the engine's samples of Pc against covariance scale, served only when it returned a Pc",
  },
  "src/components/ValidationPanel.tsx": {
    count: 4,
    why: "the NASA comparison: this node's gate-off Pc beside CARA's published Pc2D, the default outcome in its own column",
  },
  "src/components/EventDetail.tsx": {
    count: 1,
    why: "the originator's asserted Pc, labelled as theirs, not Sentinel's",
  },
};

export function barePcFormatting(file: string, text: string): Hit[] {
  return findAll(file, text, FORMATTER, (m) => NAMES_A_PC.test(m[1] ?? m[2] ?? ""));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the Pc contract scan", () => {
  it("finds a Pc formatted by hand, and leaves other numbers alone", () => {
    const code = [
      "const a = `Pc ${sciPlain(a.pc)}`;",
      "<b>{sci(s.assessment.pc_max ?? 0)}</b>",
      "{pcAtSlider.toExponential(2)}",
      "{r.sentinel_pc.toPrecision(3)}",
      "{sci(k)} {metres(a.miss_distance_m)} {v.toExponential(3)} {curve.k_star.toPrecision(3)} {pcs.length}",
    ].join("\n");
    expect(barePcFormatting("x.tsx", code).map((h) => h.line)).toEqual([1, 2, 3, 4]);
  });

  it("finds no Pc rendered outside PcValue beyond the places listed with a reason", () => {
    const found: Record<string, Hit[]> = {};
    for (const [file, text] of Object.entries(SOURCES)) {
      if (OWNERS.has(file)) continue;
      const hits = barePcFormatting(file, text);
      if (hits.length > 0) found[file] = hits;
    }
    const unexpected = Object.values(found)
      .flat()
      .filter((h) => !ALLOWED[h.file]);
    expect(unexpected, "render these through PcValue (or pcText for plain text)").toEqual([]);
    for (const [file, { count }] of Object.entries(ALLOWED)) {
      expect(found[file]?.length ?? 0, `${file}: update ALLOWED with the change`).toBe(count);
    }
  });
});

describe("renderings that used to format a Pc by hand", () => {
  it("HistorySpark's tooltip carries the method and never states a worst case of zero", () => {
    const entry = detail(summary({ assessment: { ...diluted, pc_max: null } })).history[0];
    const { container } = render(<HistorySpark history={[entry]} />);
    const tooltip = container.querySelector("circle title")?.textContent ?? "";
    expect(tooltip).toMatch(/FOSTER_ESTES_2D/);
    expect(tooltip).not.toMatch(/worst[^,;)]*\b0\b/);
  });

  it("the dilution callout never prints a zero for a Pc it was not given", async () => {
    const s = summary({ assessment: { ...diluted, pc_max: null } });
    const EVENT = s.event_id;
    mockApi({
      [`GET /api/events/${EVENT}`]: ok(detail(s)),
      [`GET /api/events/${EVENT}/encounter`]: ok({ available: false, reason: "test" }),
      [`GET /api/events/${EVENT}/dilution-curve`]: ok({ available: false }),
    });
    render(<EventDetail eventId={EVENT} version={0} />);
    const callout = (await screen.findByText("Diluted.")).parentElement!;
    expect(callout.textContent).not.toMatch(/(^|\s)0(\s|$|\.(\s|$))/); // a zero, not k* = 0.200
  });
});
