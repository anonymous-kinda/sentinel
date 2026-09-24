import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LogEntryView, OpsView } from "../api/types";
import { OpsPanel } from "../components/OpsPanel";
import { mockApi, ok } from "./fixtures/api";
import { HOSTILE, expectInert } from "./fixtures/hostile";

const EVENT = "99001-99118-20260924T070000";
const OPS = `GET /api/events/${EVENT}/ops`;

const signed = {
  lamport: 4,
  wall_time: "2026-09-24T11:07:00Z",
  event_ref: { event_id: EVENT, message_id: "EX-118-3" },
  signature_valid: true,
  review_required: false,
} as const;

const resolution = {
  ...signed,
  dot: ["hub", 4],
  digest: "d".repeat(64),
  kind: "RESOLUTION",
  author: "col.reyes@hub",
  node: "hub",
  body: {
    field: "triage_status",
    value: "MANEUVER_PLANNING",
    superseded: [
      { dot: ["alpha", 2], v: "NO_ACTION", by: "maj.ortiz@alpha", node: "alpha", at: "2026-09-24T10:40:00Z" },
      { dot: ["hub", 3], v: "WATCH", by: "capt.lee@hub", node: "hub", at: "2026-09-24T10:41:00Z" },
    ],
  },
} satisfies LogEntryView;

function view(entries: LogEntryView[]): OpsView {
  return {
    entries,
    annotations: { triage_status: { values: [], conflict: false } },
    current_ref: null,
    decisions: ["MANEUVER", "NO_MANEUVER", "MONITOR", "REQUEST_TASKING"],
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function renderEntries(entries: LogEntryView[]) {
  mockApi({ [OPS]: ok(view(entries)) });
  const result = render(<OpsPanel eventId={EVENT} version={0} readOnly />);
  await screen.findAllByText(/signed/);
  return result;
}

describe("OpsPanel - the decision log", () => {
  it("shows which field a RESOLUTION settled, and the value it set", async () => {
    await renderEntries([resolution]);
    const entry = screen.getByRole("listitem", { name: /resolution/i });
    expect(within(entry).getByText(/triage status/)).toBeTruthy();
    expect(within(entry).getByText("MANEUVER PLANNING")).toBeTruthy();
  });

  it("lists every value a RESOLUTION superseded, with who wrote it and on which node", async () => {
    await renderEntries([resolution]);
    const superseded = screen.getByRole("list", { name: "Superseded values" });
    const rows = within(superseded).getAllByRole("listitem").map((li) => li.textContent);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatch(/NO ACTION.*maj\.ortiz@alpha.*alpha/);
    expect(rows[1]).toMatch(/WATCH.*capt\.lee@hub.*hub/);
  });

  it("still shows a decision's rationale and a note's text", async () => {
    await renderEntries([
      { ...signed, dot: ["hub", 1], digest: "a".repeat(64), kind: "DECISION", author: "op@hub", node: "hub", body: { decision: "NO_MANEUVER", rationale: "miss grows" } },
      { ...signed, dot: ["hub", 2], digest: "b".repeat(64), kind: "NOTE", author: "op@hub", node: "hub", body: { text: "owner contacted" } },
    ]);
    expect(screen.getByText("NO MANEUVER")).toBeTruthy();
    expect(screen.getByText("miss grows")).toBeTruthy();
    expect(screen.getByText("owner contacted")).toBeTruthy();
  });

  it("shows and logs the server's reason when it refuses a write", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi({
      [OPS]: ok(view([])),
      [`POST /api/events/${EVENT}/annotation`]: { status: 403, body: { detail: "this node is read-only" } },
    });
    render(<OpsPanel eventId={EVENT} version={0} readOnly={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "WATCH" }));
    expect(await screen.findByText("this node is read-only")).toBeTruthy();
    expect(consoleError).toHaveBeenCalledWith(
      "Operator data write failed",
      expect.objectContaining({ event_id: EVENT, status: 403, error: "this node is read-only" }),
    );
    consoleError.mockRestore();
  });

  it("keeps the operator's rationale when the node refuses the decision", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi({
      [OPS]: ok(view([])),
      [`POST /api/events/${EVENT}/decision`]: { status: 409, body: { detail: "the CDM changed; review before deciding" } },
    });
    render(<OpsPanel eventId={EVENT} version={0} readOnly={false} />);
    const rationale = (await screen.findByRole("textbox", { name: "Rationale" })) as HTMLInputElement;
    fireEvent.change(rationale, { target: { value: "miss distance grows over three updates" } });
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));
    expect(await screen.findByText("the CDM changed; review before deciding")).toBeTruthy();
    expect(rationale.value).toBe("miss distance grows over three updates");
    vi.restoreAllMocks();
  });

  it("treats every string in a RESOLUTION as text, whoever wrote it", async () => {
    const { container } = await renderEntries([
      {
        ...resolution,
        author: HOSTILE.img,
        node: HOSTILE.attr,
        body: {
          field: HOSTILE.script,
          value: HOSTILE.img,
          superseded: [{ dot: ["x", 1], v: HOSTILE.svg, by: HOSTILE.img, node: HOSTILE.attr, at: "2026-09-24T10:40:00Z" }],
        },
      },
    ]);
    expectInert(container, [HOSTILE.script, HOSTILE.img, HOSTILE.svg, HOSTILE.attr]);
  });
});
