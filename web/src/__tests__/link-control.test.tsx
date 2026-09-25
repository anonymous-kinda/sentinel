import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LinkControl } from "../components/LinkControl";
import { mockApi, ok } from "./fixtures/api";

const LINK = {
  role: "edge",
  hub_id: "hub-1",
  monitor: { state: "CONNECTED", rtt_ms: 40, rate_bytes_per_s: 9000, seconds_since_success: 1, failures_in_row: 0, bytes_total: 1, exchanges: 1 },
  emulation: { preset: "CONNECTED", enabled: true, toxics: [] },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("LinkControl - the demo link presets", () => {
  it("shows and logs why the node refused a preset, rather than failing silently", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi({
      "GET /api/link": ok(LINK),
      "POST /api/demo/link": { status: 403, body: { detail: "link emulation controls are disabled on this node" } },
    });
    render(<LinkControl version={0} />);
    fireEvent.click(await screen.findByRole("button", { name: /LINK CONNECTED/ }));
    fireEvent.click(screen.getByRole("button", { name: "DENIED" }));
    expect((await screen.findByRole("alert")).textContent).toBe("link emulation controls are disabled on this node");
    expect(consoleError).toHaveBeenCalledWith("Link preset failed", expect.objectContaining({ preset: "DENIED", status: 403 }));
  });

  it("refetches the link after a preset is applied", async () => {
    const api = mockApi({ "GET /api/link": ok(LINK), "POST /api/demo/link": ok({ preset: "DENIED", enabled: true, toxics: [] }) });
    render(<LinkControl version={0} />);
    fireEvent.click(await screen.findByRole("button", { name: /LINK CONNECTED/ }));
    const before = api.calls("GET /api/link").length;
    fireEvent.click(screen.getByRole("button", { name: "DENIED" }));
    await vi.waitFor(() => expect(api.calls("GET /api/link").length).toBe(before + 1));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
