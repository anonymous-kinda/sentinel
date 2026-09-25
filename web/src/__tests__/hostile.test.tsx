import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { AiAnswer, EventSummary, SyncStatus } from "../api/types";
import { AnswerCard } from "../components/AssistantPanel";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { EventDetail } from "../components/EventDetail";
import { EventList } from "../components/EventList";
import { HistorySpark } from "../components/HistorySpark";
import { SyncPanel } from "../components/SyncPanel";
import { ImagerCatalog } from "../components/passes/ImagerCatalog";
import { PassGantt } from "../components/passes/PassGantt";
import { mockApi, ok } from "./fixtures/api";
import { detail, diluted, hubNode, refused, summary } from "./fixtures/events";
import { HOSTILE, expectInert } from "./fixtures/hostile";
import { NOW_MS, catalog, passes } from "./fixtures/passes";
import { FakeEventSource } from "./fixtures/stream";

/**
 * Every string that arrives from outside the console - CDM object names and
 * originators an operator uploaded, AI answer text, server error details,
 * sync event ids, imager names from an element set - rendered with a
 * payload that would run script if it reached the DOM as markup or as an
 * attribute. Each must arrive as inert text.
 */

vi.mock("../components/Globe", () => ({ Globe: () => <div data-testid="globe" /> }));

const { script, img, svg, attr, url } = HOSTILE;

function hostileSummary(): EventSummary {
  return summary({
    event_id: url,
    primary: { id: "99001", name: script },
    secondary: { id: attr, name: null },
    originator: img,
    originator_pc: 1e-3,
    latest_message_id: svg,
    voice: img,
    assessment: { ...refused, refusal_reason: script as never, diagnostics: { [img]: svg, missing_covariance_for: [attr] } },
  });
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("hostile strings arrive as text", () => {
  it("(the check itself catches markup that became elements)", () => {
    const { container } = render(<div dangerouslySetInnerHTML={{ __html: `<b onclick="void 0">x</b>` }} />);
    expect(() => expectInert(container, [])).toThrow(/event handler/);
  });

  it("in the event list: object names, ids and the refusal reason", () => {
    const { container } = render(<EventList events={[hostileSummary()]} selected={null} onSelect={() => {}} mode="active" />);
    expectInert(container, [script, attr]);
  });

  it("in the event detail: names, originator, message id, warnings and refusal diagnostics", async () => {
    const s = hostileSummary();
    const d = detail(s);
    d.history[0].warnings = [{ code: script, detail: img }];
    d.history[0].hbr_source = svg;
    d.engine_version = attr;
    const path = `/api/events/${encodeURIComponent(s.event_id)}`;
    mockApi({
      [`GET ${path}`]: ok(d),
      [`GET ${path}/encounter`]: ok({ available: false, reason: img }),
      [`GET ${path}/dilution-curve`]: ok({ available: false }),
    });
    const { container } = render(<EventDetail eventId={s.event_id} version={0} />);
    await screen.findByText("Provenance");
    expectInert(container, [script, img, svg, attr]);
  });

  it("in a hub-asserted summary: who asserted it and its voice line", async () => {
    const s = { ...hostileSummary(), verification: "HUB_ASSERTED" as const };
    const path = `/api/events/${encodeURIComponent(s.event_id)}`;
    mockApi({
      [`GET ${path}`]: ok({ ...detail(s), history: [], asserted_by: svg }),
      [`GET ${path}/encounter`]: ok({ available: false }),
      [`GET ${path}/dilution-curve`]: ok({ available: false }),
    });
    const { container } = render(<EventDetail eventId={s.event_id} version={0} />);
    await screen.findByText(/not computed here/);
    expectInert(container, [script, img, svg]);
  });

  it("in an AI answer: its text, fallbacks, withheld numbers and one-click choices", () => {
    const answer: AiAnswer = {
      status: "clarify",
      text: script,
      tier: { router: "deterministic", narrator: "template", reason: img, link_state: "DENIED", marking: "UNCLASSIFIED" },
      route: null,
      facts: null,
      narrated_by: svg,
      grounding: { ok: false, unsupported: [attr] },
      withheld: { narrator: img, unsupported: [svg] },
      alternatives: [{ event_id: url, label: img, p: 0.5 }],
      fallbacks: [{ from: attr, to: svg, reason: script }],
      draft_id: null,
      audit_seq: null,
    };
    const { container } = render(<AnswerCard answer={answer} onAsk={() => {}} onConfirm={async () => ({})} />);
    expectInert(container, [script, img, svg, attr]);
  });

  it("in a server error caught by a panel's boundary", () => {
    function Throws(): never {
      throw new Error(img);
    }
    const { container } = render(
      <ErrorBoundary label={script}>
        <Throws />
      </ErrorBoundary>,
    );
    expectInert(container, [script, img]);
  });

  it("in the sync queue and arrivals: event ids, the hub id and statuses", async () => {
    const status: SyncStatus = {
      role: "edge",
      mode: "edf",
      hub_id: script,
      link: { state: "LIMITED", rtt_ms: 900, rate_bytes_per_s: 700, seconds_since_success: 2, failures_in_row: 0, bytes_total: 1, exchanges: 1 },
      queue: [{ event_id: img, sha: "a", bytes: 1, class: svg, deadline: null, seconds_to_deadline: null, latest: true, status: attr, eta_s: null }],
      arrivals: [{ event_id: img, sha: "b", class: "URGENT", latest: true, bytes: 1, wall_s: 1, node_time: "", deadline: null, hash_ok: true, status: "ok", verification: svg }],
      arrivals_total: 1,
    };
    mockApi({ "GET /api/sync": ok(status) });
    const { container } = render(<SyncPanel version={0} />);
    await screen.findByText("Arrivals");
    // Event ids are cut to 22 characters, and class and status read "_" as
    // a space; what is left is still text.
    expectInert(container, [script, svg]);
    expect(container.textContent).toContain(img.slice(0, 22));
    expect(container.textContent).toContain("autofocus onfocus=");
  });

  it("in a Pc tooltip: the message id", () => {
    const entry = { ...detail(summary({ assessment: diluted })).history[0], message_id: script };
    const { container } = render(<HistorySpark history={[entry]} />);
    expectInert(container, [script]);
  });

  it("in the pass timeline and imaging catalog: imager names, sensors and sources", () => {
    const window = { ...passes.windows[0], name: img };
    const view = { ...passes, label: script, windows: [window] };
    const gantt = render(<PassGantt view={view} nowMs={NOW_MS} />);
    fireEvent.focus(screen.getAllByRole("img", { name: /rise/ })[0]);
    expectInert(gantt.container, [img, script]);
    gantt.unmount();

    const hostileCatalog = {
      imagers: [{ ...catalog.imagers[0], name: svg, basis: attr }],
      skipped: [{ norad_id: 1, name: script, reason: img }],
    };
    const list = render(<ImagerCatalog catalog={hostileCatalog} />);
    expectInert(list.container, [svg, attr, script, img]);
  });

  it("in the live feed: names in an accepted CDM, and a rejection's code and source", async () => {
    FakeEventSource.install();
    mockApi({
      "GET /api/node": ok(hubNode),
      "GET /api/link": ok({ role: "hub", hub_id: null, monitor: { state: "UNKNOWN", rtt_ms: null } }),
      "GET /api/events?scope=active": ok([]),
    });
    const { container } = render(<App />);
    await screen.findByText("Live feed");
    act(() => FakeEventSource.latest().open());
    act(() => FakeEventSource.latest().emit("cdm.accepted", hostileSummary()));
    act(() => FakeEventSource.latest().emit("cdm.rejected", { code: img, source: svg }));
    await screen.findByText(/CDM quarantined/);
    expectInert(container, [script, attr, img, svg]);
  });
});
