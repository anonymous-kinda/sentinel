import { describe, expect, it } from "vitest";
import {
  intervalHours,
  meetsReactionTime,
  skipReasonText,
  validateUnit,
  windowKind,
  type UnitDraft,
} from "../lib/passes";
import { ganttLayout, hourTicks, imagerRows, labelEvery, timeScale, zuluHour } from "../lib/timeline";
import { NOW_MS, dayEO, gaps, nightEO, passes, sar, staleEO } from "./fixtures/passes";

const ms = (iso: string) => Date.parse(iso);

describe("the fixture is internally consistent (hand-written, so checked)", () => {
  it("each gap's duration is its end minus its start", () => {
    for (const g of gaps) expect((ms(g.end) - ms(g.start)) / 1000).toBe(g.duration_s);
  });
  it("gaps are bounded by padded usable windows, never by the night pass", () => {
    const edges = new Set(gaps.flatMap((g) => [g.start, g.end]));
    for (const w of [sar, dayEO, staleEO]) expect(edges.has(w.padded_start) && edges.has(w.padded_end)).toBe(true);
    expect(edges.has(nightEO.padded_start)).toBe(false);
  });
});

describe("windowKind - three kinds the legend names", () => {
  it("separates usable EO, usable SAR and EO at night", () => {
    expect(windowKind(dayEO)).toBe("eo");
    expect(windowKind(sar)).toBe("sar");
    expect(windowKind(nightEO)).toBe("unusable");
  });
});

describe("meetsReactionTime", () => {
  const gap = gaps[1]; // 11:30:06 to 18:00:45
  it("is true when the window left before or during it is at least the reaction time", () => {
    expect(meetsReactionTime(gap, 30, NOW_MS)).toBe(true);
  });
  it("counts an open window from now, not from its start", () => {
    const late = ms(gap.end) - 29 * 60_000;
    expect(meetsReactionTime(gap, 30, late)).toBe(false);
    expect(meetsReactionTime(gap, 29, late)).toBe(true);
  });
});

describe("intervalHours", () => {
  it("reads the horizon from the reply's start and end", () => {
    expect(intervalHours(passes)).toBe(24);
  });
});

describe("skipReasonText", () => {
  it("explains the engine's skip reasons and passes unknown ones through", () => {
    expect(skipReasonText("missing")).toMatch(/no element set/);
    expect(skipReasonText("name_mismatch")).toMatch(/different object/);
    expect(skipReasonText("decayed")).toBe("decayed");
  });
});

describe("validateUnit - mirrors the ICD's 422 rules", () => {
  const good: UnitDraft = { unit_id: " EX-UNIT-1 ", lat_deg: "35.26", lon_deg: "-116.68", alt_m: "700", reaction_time_min: "30" };

  it("returns a typed unit with a trimmed id when the draft is valid", () => {
    expect(validateUnit(good)).toEqual({
      unit: { unit_id: "EX-UNIT-1", lat_deg: 35.26, lon_deg: -116.68, alt_m: 700, reaction_time_min: 30 },
      errors: {},
    });
  });

  it.each([
    ["unit_id", "  ", /required/],
    ["lat_deg", "90.5", /-90/],
    ["lat_deg", "north", /number/],
    ["lon_deg", "-180.01", /-180/],
    ["reaction_time_min", "0", /positive/],
    ["reaction_time_min", "-5", /positive/],
    ["alt_m", "", /number/],
  ] as const)("rejects %s = %j", (field, value, message) => {
    const result = validateUnit({ ...good, [field]: value });
    expect(result.unit).toBeUndefined();
    expect(result.errors[field]).toMatch(message);
  });

  it("accepts the boundaries", () => {
    expect(validateUnit({ ...good, lat_deg: "-90", lon_deg: "180" }).unit).toBeDefined();
  });
});

describe("timeScale", () => {
  const scale = timeScale(ms(passes.start), ms(passes.end), 100, 580);
  it("maps the interval onto the plot", () => {
    expect(scale(ms(passes.start))).toBe(100);
    expect(scale(ms(passes.end))).toBe(580);
    expect(scale(ms("2026-09-24T18:00:00Z"))).toBe(340);
  });
  it("clamps times outside the interval to its edges", () => {
    expect(scale(ms("2026-09-24T05:00:00Z"))).toBe(100);
    expect(scale(ms("2026-09-26T00:00:00Z"))).toBe(580);
  });
});

describe("hour ticks in Zulu", () => {
  it("puts a tick on every whole UTC hour in the interval", () => {
    const ticks = hourTicks(ms("2026-09-24T06:20:00Z"), ms("2026-09-24T09:00:00Z"));
    expect(ticks.map(zuluHour)).toEqual(["07Z", "08Z", "09Z"]);
  });
  it("labels fewer hours when the plot is narrow", () => {
    expect(labelEvery(40)).toBe(1);
    expect(labelEvery(20)).toBe(2);
    expect(labelEvery(12)).toBe(3);
    expect(labelEvery(5)).toBe(6);
  });
});

describe("imagerRows", () => {
  it("gives one row per imager, in order of its first rise, with all its windows", () => {
    const rows = imagerRows(passes.windows);
    expect(rows.map((r) => [r.name, r.sensor, r.windows.length])).toEqual([
      ["WORLDVIEW-3 (WV-3)", "EO", 2],
      ["TERRASAR-X", "SAR", 1],
      ["SENTINEL-2A", "EO", 1],
    ]);
  });
  it("is empty with no windows", () => {
    expect(imagerRows([])).toEqual([]);
  });
});

describe("ganttLayout", () => {
  it("stacks the gap band, then one row per imager, then the axis", () => {
    const layout = ganttLayout(3, 900);
    expect(layout.plotX0).toBeGreaterThan(0);
    expect(layout.plotX1).toBeLessThan(900);
    expect(layout.rowY(0)).toBeGreaterThanOrEqual(layout.bandY + layout.bandH);
    expect(layout.rowY(1) - layout.rowY(0)).toBe(layout.rowH);
    expect(layout.axisY).toBeGreaterThanOrEqual(layout.rowY(2) + layout.rowH);
    expect(layout.height).toBeGreaterThan(layout.axisY);
  });
  it("keeps a usable plot on a narrow screen", () => {
    const layout = ganttLayout(1, 320);
    expect(layout.plotX1 - layout.plotX0).toBeGreaterThanOrEqual(160);
  });
});
