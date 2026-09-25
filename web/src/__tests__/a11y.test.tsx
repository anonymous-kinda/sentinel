import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AssistantPanel } from "../components/AssistantPanel";
import { HistorySpark } from "../components/HistorySpark";
import { LinkControl } from "../components/LinkControl";
import { ValidationPanel } from "../components/ValidationPanel";
import { UnitForm } from "../components/passes/UnitForm";
import { mockApi, ok } from "./fixtures/api";
import { assessment, detail, diluted, hubNode, summary } from "./fixtures/events";
import { unit } from "./fixtures/passes";
import { FakeEventSource } from "./fixtures/stream";

vi.mock("../components/Globe", () => ({ Globe: () => <div data-testid="globe" /> }));

const CONTROL_ROLES = ["button", "textbox", "combobox", "listbox", "option", "slider", "spinbutton", "tab", "checkbox", "radio", "link"];

/** Every control a keyboard or screen-reader user can reach has a name. */
function unnamedControls(container: HTMLElement): string[] {
  return CONTROL_ROLES.flatMap((role) =>
    within(container)
      .queryAllByRole(role, { name: "" })
      .map((c) => `${role}: ${c.outerHTML.slice(0, 80)}`),
  );
}

const EVENT = summary().event_id;

beforeEach(() => {
  FakeEventSource.install();
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("controls have names", () => {
  it("(the check itself finds an unnamed control)", () => {
    const { container } = render(
      <div>
        <button />
        <input />
        <button aria-label="named" />
      </div>,
    );
    expect(unnamedControls(container)).toHaveLength(2);
  });

  it("in the operations view, with the triage and decision controls", async () => {
    mockApi({
      "GET /api/node": ok({ ...hubNode, read_only: false }),
      "GET /api/link": ok({ role: "hub", hub_id: null, monitor: { state: "UNKNOWN", rtt_ms: null } }),
      "GET /api/events?scope=active": ok([summary()]),
      [`GET /api/events/${EVENT}`]: ok(detail()),
      [`GET /api/events/${EVENT}/encounter`]: ok({ available: false }),
      [`GET /api/events/${EVENT}/dilution-curve`]: ok({ model_applies: true, log10_k: [-1, 0, 1], pc: [1e-6, 3.6e-5, 1e-5], k_star: 0.9, pc_at_k1: 3.6e-5, pc_max: 4e-5 }),
      [`GET /api/events/${EVENT}/trajectory`]: "pending",
      [`GET /api/events/${EVENT}/ops`]: ok({ entries: [], annotations: { triage_status: { values: [], conflict: false } }, current_ref: null, decisions: ["MONITOR"] }),
    });
    const { container } = render(<App />);
    await screen.findByRole("button", { name: "Record decision" });
    await screen.findByRole("slider");
    expect(unnamedControls(container)).toEqual([]);
  });

  it("in the assistant", async () => {
    mockApi({
      "GET /api/ai/status": ok({ enabled: true }),
      "GET /api/ai/audit/verify": ok({ ok: true, count: 0 }),
    });
    const { container } = render(<AssistantPanel version={0} />);
    await screen.findByRole("textbox", { name: "question" });
    expect(unnamedControls(container)).toEqual([]);
  });

  it("in the unit form while editing", () => {
    const { container } = render(<UnitForm unit={unit} readOnly={false} onSave={async () => {}} onDelete={async () => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(unnamedControls(container)).toEqual([]);
  });
});

describe("state is announced, not only drawn", () => {
  it("the link chip says whether its presets are open", async () => {
    mockApi({
      "GET /api/link": ok({
        role: "edge",
        hub_id: "hub-1",
        monitor: { state: "LIMITED", rtt_ms: 900, rate_bytes_per_s: 700, seconds_since_success: 3 },
        emulation: { preset: "LIMITED", enabled: true, toxics: [] },
      }),
    });
    render(<LinkControl version={0} />);
    const chip = await screen.findByRole("button", { name: /LINK LIMITED/ });
    expect(chip.getAttribute("aria-expanded")).toBe("false");
    act(() => chip.click());
    expect(chip.getAttribute("aria-expanded")).toBe("true");
  });

  it("the applied preset is marked as pressed, not only coloured", async () => {
    mockApi({
      "GET /api/link": ok({
        role: "edge",
        hub_id: "hub-1",
        monitor: { state: "LIMITED", rtt_ms: 900, rate_bytes_per_s: 700, seconds_since_success: 3 },
        emulation: { preset: "LIMITED", enabled: true, toxics: [] },
      }),
    });
    render(<LinkControl version={0} />);
    fireEvent.click(await screen.findByRole("button", { name: /LINK LIMITED/ }));
    expect(screen.getByRole("button", { name: "LIMITED" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "DENIED" }).getAttribute("aria-pressed")).toBe("false");
  });
});

describe("colour is never the only signal", () => {
  it("a diluted update in the Pc history has its own shape", () => {
    const history = [
      detail(summary({ assessment })).history[0],
      { ...detail(summary({ assessment: diluted })).history[0], sha256: "e".repeat(64) },
    ];
    const { container } = render(<HistorySpark history={history} />);
    const plain = container.querySelector(".spark-dot:not(.spark-dot-diluted)")!;
    const dilutedMark = container.querySelector(".spark-dot-diluted")!;
    expect(dilutedMark.tagName).not.toBe(plain.tagName);
  });

  it("the validation scatter marks CARA's 2D-invalid cases by shape, and names both in a legend", async () => {
    const row = { primary: "HST", secondary: "DEB", sentinel_pc: 1e-4, cara_pc2d: 1e-4, cara_nc3d: 1e-4, rel_error: 1e-9, relative_speed_m_s: 7000, refusal_reason: null };
    mockApi({
      "GET /api/validation": ok({
        available: true,
        operational_count: 2,
        worst_rel_error: 1e-9,
        alfano_worst_rel_error: 1e-9,
        confusion: { tp: 1, fn: 0, fp: 0, tn: 1 },
        rows: [
          { ...row, case_id: "valid", cara_says_2d_valid: true, sentinel_default: "FOSTER_ESTES_2D" },
          { ...row, case_id: "invalid", cara_says_2d_valid: false, sentinel_default: "REFUSED", refusal_reason: "LOW_RELATIVE_VELOCITY" },
        ],
      }),
    });
    const { container } = render(<ValidationPanel />);
    await screen.findByRole("img", { name: /Sentinel Pc against CARA/ });
    const valid = container.querySelector(".pt-valid")!;
    const invalid = container.querySelector(".pt-invalid")!;
    expect(invalid.tagName).not.toBe(valid.tagName);
    expect(screen.getByText(/CARA: 2D valid/, { selector: "figcaption *, figcaption" })).toBeTruthy();
    expect(screen.getByText(/CARA: 2D invalid/, { selector: "figcaption *, figcaption" })).toBeTruthy();
  });
});
