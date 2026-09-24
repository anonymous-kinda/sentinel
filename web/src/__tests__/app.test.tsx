import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { NodeInfo } from "../api/types";
import { registerTab } from "../extensions";
import { mockApi, ok, type Route } from "./fixtures/api";
import { assessment, detail, diluted, hubNode, summary } from "./fixtures/events";
import { FakeEventSource } from "./fixtures/stream";

// The globe needs WebGL, which jsdom has not got; it has its own boundary.
vi.mock("../components/Globe", () => ({ Globe: () => <div data-testid="globe" /> }));

function Explodes(): never {
  throw new TypeError("Cannot read properties of undefined (reading 'queue')");
}
registerTab({ id: "broken", label: "Broken", module: "broken-module", render: () => <Explodes /> });

const EVENT = summary().event_id;
const EVENTS = "GET /api/events?scope=active";

function routes(node: NodeInfo = hubNode, extra: Record<string, Route> = {}): Record<string, Route> {
  return {
    "GET /api/node": ok(node),
    "GET /api/link": ok({ role: node.role, hub_id: null, monitor: { state: "UNKNOWN", rtt_ms: null } }),
    [EVENTS]: ok([summary()]),
    "GET /api/events?scope=past": ok([]),
    [`GET /api/events/${EVENT}`]: ok(detail()),
    [`GET /api/events/${EVENT}/encounter`]: ok({ available: false, reason: "test" }),
    [`GET /api/events/${EVENT}/dilution-curve`]: ok({ available: false }),
    [`GET /api/events/${EVENT}/trajectory`]: "pending",
    [`GET /api/events/${EVENT}/ops`]: ok({ entries: [], annotations: { triage_status: { values: [], conflict: false } }, current_ref: null, decisions: [] }),
    ...extra,
  };
}

function renderApp(hash = "", api: Record<string, Route> = routes()) {
  window.location.hash = hash;
  const mocked = mockApi(api);
  const result = render(<App />);
  return { ...result, api: mocked };
}

const banners = (container: HTMLElement) => [...container.querySelectorAll(".banner")].map((b) => b.textContent);

beforeEach(() => {
  FakeEventSource.install();
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("App - classification marking", () => {
  it("never shows a marking the node has not reported", () => {
    const { container } = renderApp("", { ...routes(), "GET /api/node": "pending" });
    for (const text of banners(container)) {
      expect(text).not.toMatch(/UNCLASSIFIED/);
      expect(text).toMatch(/MARKING UNKNOWN/);
    }
  });

  it("shows the node's own marking, top and bottom, once it has reported", async () => {
    const { container } = renderApp("", routes({ ...hubNode, marking: "SECRET // EXERCISE" }));
    await waitFor(() => expect(banners(container)).toEqual(["SECRET // EXERCISE", "SECRET // EXERCISE"]));
  });

  it("colours the banner by the marking's level, never green for a marking it cannot read as UNCLASSIFIED", async () => {
    const tones = (container: HTMLElement) => [...container.querySelectorAll(".banner")].map((b) => b.className);
    const pending = renderApp("", { ...routes(), "GET /api/node": "pending" });
    expect(tones(pending.container).every((c) => c.includes("banner-unknown"))).toBe(true);
    pending.unmount();

    const secret = renderApp("", routes({ ...hubNode, marking: "SECRET // EXERCISE" }));
    await waitFor(() => expect(tones(secret.container).every((c) => c.includes("banner-secret"))).toBe(true));
    secret.unmount();

    const unclassified = renderApp("", routes());
    await waitFor(() => expect(tones(unclassified.container).every((c) => c.includes("banner-unclassified"))).toBe(true));
  });
});

describe("App - a failing panel never blanks the console", () => {
  it("contains a module tab that throws, and the other tabs still work", async () => {
    renderApp("#broken", routes({ ...hubNode, modules: [...hubNode.modules, "broken-module"] }));
    expect(await screen.findByText(/Broken unavailable: TypeError/)).toBeTruthy();
    expect(screen.getAllByText("UNCLASSIFIED // EXERCISE")).toHaveLength(2);
    fireEvent.click(screen.getByRole("tab", { name: "Operations" }));
    expect(await screen.findByText("Active conjunctions")).toBeTruthy();
  });

  it("contains a validation reply it cannot draw", async () => {
    renderApp("#validation", {
      ...routes(),
      "GET /api/validation": ok({ available: true, confusion: { tp: 1, fn: 0, fp: 0, tn: 1 }, rows: [{ case_id: "c1" }] }),
    });
    expect(await screen.findByText(/Validation unavailable/)).toBeTruthy();
    expect(screen.getByRole("tablist")).toBeTruthy();
  });

  it("contains an event list it cannot draw", async () => {
    renderApp("", { ...routes(), [EVENTS]: ok([{ ...summary(), band: null }]) });
    expect(await screen.findByText(/Event list unavailable/)).toBeTruthy();
    expect(screen.getByRole("tablist")).toBeTruthy();
  });
});

describe("App - tabs", () => {
  it("opens Operations when the bookmarked tab is a module this node does not run", async () => {
    renderApp("#passes");
    expect(await screen.findByText("Active conjunctions")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Operations" }).getAttribute("aria-selected")).toBe("true");
  });
});

describe("App - the live stream", () => {
  it("says in words whether the stream is live, not by colour alone", async () => {
    renderApp();
    const status = await screen.findByRole("status", { name: /stream/i });
    expect(status.textContent).toMatch(/no stream/i);
    act(() => FakeEventSource.latest().open());
    expect(status.textContent).toMatch(/live/i);
  });

  it("refetches what it shows when the stream reopens, since events sent while it was down are lost", async () => {
    const { api } = renderApp();
    await screen.findByText("Active conjunctions");
    await waitFor(() => expect(api.calls(EVENTS).length).toBeGreaterThan(0));
    const before = api.calls(EVENTS).length;
    act(() => FakeEventSource.latest().open());
    await waitFor(() => expect(api.calls(EVENTS).length).toBe(before + 1));
  });

  it("shows a streamed Pc through PcValue: with its worst case when diluted, never as a bare number", async () => {
    renderApp();
    const feed = (await screen.findByText("Live feed")).parentElement!;
    act(() => FakeEventSource.latest().open());
    act(() => FakeEventSource.latest().emit("cdm.accepted", summary({ assessment: diluted })));
    const row = await within(feed).findByText(/CDM 3/);
    expect(row.textContent).toMatch(/worst 2\.0×10⁻⁴/);
    expect(row.querySelector(".pc")?.getAttribute("title")).toBe(`method ${assessment.method}`);
    expect(feed.textContent).not.toMatch(/3\.6e-5/);
  });
});
