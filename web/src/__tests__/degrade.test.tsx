import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EventDetail } from "../components/EventDetail";
import { EventList } from "../components/EventList";
import { OpsPanel } from "../components/OpsPanel";
import { SyncPanel } from "../components/SyncPanel";
import { ValidationPanel } from "../components/ValidationPanel";
import { mockApi } from "./fixtures/api";
import { summary } from "./fixtures/events";

/** A panel whose endpoint fails - a 404 for a module this node does not
 *  run, a 5xx, no route - says so, rather than loading for ever. */

const NOT_FOUND = { status: 404, body: { detail: "Not Found" } };
const EVENT = "99001-99118-20260924T070000";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("a panel whose endpoint fails says why", () => {
  it("Sync", async () => {
    mockApi({ "GET /api/sync": NOT_FOUND });
    render(<SyncPanel version={0} />);
    expect((await screen.findByRole("alert")).textContent).toBe("Sync status unavailable: Not Found");
    expect(screen.queryByText(/Loading/)).toBeNull();
  });

  it("Validation", async () => {
    mockApi({ "GET /api/validation": { status: 500, body: { detail: "validation bundle unreadable" } } });
    render(<ValidationPanel />);
    expect((await screen.findByRole("alert")).textContent).toBe("NASA comparison unavailable: validation bundle unreadable");
    expect(screen.queryByText(/Running the NASA comparison/)).toBeNull();
  });

  it("Event detail", async () => {
    mockApi({
      [`GET /api/events/${EVENT}`]: { status: 404, body: { detail: "no such event" } },
      [`GET /api/events/${EVENT}/encounter`]: NOT_FOUND,
      [`GET /api/events/${EVENT}/dilution-curve`]: NOT_FOUND,
    });
    render(<EventDetail eventId={EVENT} version={0} />);
    expect((await screen.findByRole("alert")).textContent).toBe("Event unavailable: no such event");
    expect(screen.queryByText(/Loading/)).toBeNull();
  });

  it("Triage and decisions", async () => {
    mockApi({ [`GET /api/events/${EVENT}/ops`]: { status: 500, body: { detail: "operator log unreadable" } } });
    render(<OpsPanel eventId={EVENT} version={0} readOnly={false} />);
    expect((await screen.findByRole("alert")).textContent).toBe("Triage and decisions unavailable: operator log unreadable");
    expect(screen.queryByText(/Loading/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Record decision" })).toBeNull();
  });

  it("still says Loading while the request is in flight", () => {
    mockApi({ "GET /api/sync": "pending" });
    render(<SyncPanel version={0} />);
    expect(screen.getByText("Loading…")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("a value this console does not know", () => {
  it("shows a verification state it has no text for by name, rather than failing the list", () => {
    const event = summary({ verification: "RECONCILING" as never });
    render(<EventList events={[event]} selected={null} onSelect={() => {}} mode="active" />);
    expect(screen.getByText("RECONCILING")).toBeTruthy();
    expect(screen.getByText("EX-DEB 118")).toBeTruthy();
  });
});
