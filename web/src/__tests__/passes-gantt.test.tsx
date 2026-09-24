import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PassGantt } from "../components/passes/PassGantt";
import { WINDOW_KIND_LABEL } from "../lib/passes";
import { GAP_LABEL, NOW_MS, passes } from "./fixtures/passes";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const windowNamed = (name: RegExp) => screen.getAllByRole("img", { name });
const num = (el: Element | null, attr: string) => Number(el?.getAttribute(attr));

describe("PassGantt - 24 h of passes over the unit", () => {
  it("draws one row per imager with its name and a sensor chip", () => {
    const { container } = render(<PassGantt view={passes} nowMs={NOW_MS} />);
    const labels = [...container.querySelectorAll(".gantt-row-name")].map((n) => n.textContent);
    expect(labels).toEqual(["WORLDVIEW-3 (WV-3)", "TERRASAR-X", "SENTINEL-2A"]);
    const chips = [...container.querySelectorAll(".gantt-chip-text")].map((n) => n.textContent);
    expect(chips).toEqual(["EO", "SAR", "EO"]);
  });

  it("makes every window keyboard-focusable with a spoken description", () => {
    render(<PassGantt view={passes} nowMs={NOW_MS} />);
    const windows = windowNamed(/rise/);
    expect(windows).toHaveLength(4);
    for (const w of windows) expect(w.getAttribute("tabindex")).toBe("0");
    expect(windowNamed(/TERRASAR-X: SAR: usable/)).toHaveLength(1);
    expect(windowNamed(/WORLDVIEW-3 \(WV-3\): EO at night: not usable/)).toHaveLength(1);
  });

  it("tells the three kinds apart by shape and legend text, not colour alone", () => {
    const { container } = render(<PassGantt view={passes} nowMs={NOW_MS} />);
    const kinds = [...container.querySelectorAll("[data-kind]")].map((n) => n.getAttribute("data-kind"));
    expect(kinds).toEqual(["unusable", "eo", "sar", "eo"]);
    for (const label of Object.values(WINDOW_KIND_LABEL)) expect(screen.getByText(label)).toBeTruthy();
    expect(screen.getByText(/hatched: element set older than 3 days/)).toBeTruthy();
    expect(screen.getByText(/lighter ends: timing pad/)).toBeTruthy();
  });

  it("draws the padded extent around the rise-set core", () => {
    render(<PassGantt view={passes} nowMs={NOW_MS} />);
    const [win] = windowNamed(/TERRASAR-X/);
    const pad = win.querySelector(".win-pad");
    const core = win.querySelector(".win-core");
    expect(num(pad, "x")).toBeLessThan(num(core, "x"));
    expect(num(pad, "width")).toBeGreaterThan(num(core, "width"));
  });

  it("hatches windows from stale element sets, and only those", () => {
    render(<PassGantt view={passes} nowMs={NOW_MS} />);
    expect(windowNamed(/SENTINEL-2A/)[0].querySelector(".hatch")).not.toBeNull();
    expect(windowNamed(/TERRASAR-X/)[0].querySelector(".hatch")).toBeNull();
  });

  it("shows the gaps in a top band labelled exactly with the ICD's label", () => {
    const { container } = render(<PassGantt view={passes} nowMs={NOW_MS} />);
    expect(container.querySelector(".gantt-caption")?.textContent).toBe(GAP_LABEL);
    const gaps = screen.getAllByRole("img", { name: new RegExp(`^${GAP_LABEL}`) });
    expect(gaps).toHaveLength(4);
    expect(gaps.filter((g) => g.querySelector(".hatch"))).toHaveLength(2); // the two low-confidence gaps
    expect(gaps[1].getAttribute("aria-label")).toContain("241130Z SEP 26 to 241800Z SEP 26");
  });

  it("marks now, and labels whole hours in Zulu", () => {
    render(<PassGantt view={passes} nowMs={NOW_MS} />);
    expect(screen.getByText("now")).toBeTruthy();
    expect(screen.getByText("12Z")).toBeTruthy();
    expect(screen.getByText("18Z")).toBeTruthy();
  });

  it("draws no now line when now is outside the interval", () => {
    render(<PassGantt view={passes} nowMs={Date.parse("2026-09-26T00:00:00Z")} />);
    expect(screen.queryByText("now")).toBeNull();
  });

  it("shows rise, culmination and set, elevation, mask, element age and pad on focus or hover", () => {
    render(<PassGantt view={passes} nowMs={NOW_MS} />);
    expect(screen.getByText(/Hover or focus a pass/)).toBeTruthy();
    const [night, day] = windowNamed(/WORLDVIEW-3/);
    fireEvent.focus(day);
    for (const text of ["241802Z SEP 26", "241806Z SEP 26", "241810Z SEP 26", "61.2°", "40.3°", "0.5 d", "±75 s"]) {
      expect(screen.getByText(text)).toBeTruthy();
    }
    fireEvent.mouseEnter(night);
    expect(screen.getByText("240730Z SEP 26")).toBeTruthy();
  });

  it("keeps the details current when a refetch brings new numbers for the same pass", () => {
    const { rerender } = render(<PassGantt view={passes} nowMs={NOW_MS} />);
    fireEvent.focus(windowNamed(/TERRASAR-X/)[0]);
    expect(screen.getByText("52.0°")).toBeTruthy();
    const refreshed = { ...passes, windows: passes.windows.map((w) => (w.norad_id === 31698 ? { ...w, max_elevation_deg: 53.4 } : w)) };
    rerender(<PassGantt view={refreshed} nowMs={NOW_MS} />);
    expect(screen.getByText("53.4°")).toBeTruthy();
    expect(screen.queryByText("52.0°")).toBeNull();
  });

  function containerWidth(width: number) {
    class FixedWidth {
      constructor(private readonly callback: ResizeObserverCallback) {}
      observe() {
        this.callback([{ contentRect: { width } } as ResizeObserverEntry], this as unknown as ResizeObserver);
      }
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", FixedWidth);
  }

  it("fits the width of its container", () => {
    containerWidth(480);
    const { container } = render(<PassGantt view={passes} nowMs={NOW_MS} />);
    expect(container.querySelector("svg")?.getAttribute("width")).toBe("480");
  });

  it("shortens imager names on a narrow screen, keeping the full name as a tooltip", () => {
    containerWidth(400);
    const { container } = render(<PassGantt view={passes} nowMs={NOW_MS} />);
    const [wv3] = [...container.querySelectorAll(".gantt-row")];
    const name = wv3.querySelector(".gantt-row-name")?.textContent ?? "";
    expect(name).toMatch(/^WORLD.*…$/);
    expect(name.length).toBeLessThanOrEqual(6);
    expect(wv3.querySelector("title")?.textContent).toBe("WORLDVIEW-3 (WV-3)");
  });

  it("says so when no catalogued imager passes in the interval", () => {
    const empty = { ...passes, windows: [], gaps: [{ ...passes.gaps[0], end: passes.end, duration_s: 86400 }] };
    render(<PassGantt view={empty} nowMs={NOW_MS} />);
    expect(screen.getByText(/No catalogued imager passes over the unit/)).toBeTruthy();
  });
});
