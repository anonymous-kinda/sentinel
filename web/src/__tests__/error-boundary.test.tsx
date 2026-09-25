import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "../components/ErrorBoundary";

function Panel({ broken }: { broken: boolean }) {
  if (broken) throw new TypeError("Cannot read properties of undefined (reading 'state')");
  return <div>panel content</div>;
}

let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ErrorBoundary - a failing panel degrades to a notice", () => {
  it("names the panel and the error, and says the rest of the console is unaffected", () => {
    render(
      <ErrorBoundary label="Sync">
        <Panel broken />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/Sync unavailable: TypeError: Cannot read properties of undefined/)).toBeTruthy();
    expect(screen.getByText(/The rest of the console is unaffected/)).toBeTruthy();
  });

  it("logs the failure with a stable message and the panel in a field", () => {
    render(
      <ErrorBoundary label="Sync">
        <Panel broken />
      </ErrorBoundary>,
    );
    expect(consoleError).toHaveBeenCalledWith(
      "Panel render failed",
      expect.objectContaining({ panel: "Sync", error: "TypeError: Cannot read properties of undefined (reading 'state')" }),
    );
  });

  it("recovers when what it shows changes: one malformed event must not blank the pane for every other", () => {
    const { rerender } = render(
      <ErrorBoundary label="Event detail" resetKey="event-A">
        <Panel broken />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/Event detail unavailable/)).toBeTruthy();

    rerender(
      <ErrorBoundary label="Event detail" resetKey="event-B">
        <Panel broken={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("panel content")).toBeTruthy();
    expect(screen.queryByText(/unavailable/)).toBeNull();
  });

  it("stays on the notice while the reset key is unchanged", () => {
    const { rerender } = render(
      <ErrorBoundary label="Event detail" resetKey="event-A">
        <Panel broken />
      </ErrorBoundary>,
    );
    rerender(
      <ErrorBoundary label="Event detail" resetKey="event-A">
        <Panel broken={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/Event detail unavailable/)).toBeTruthy();
  });
});
