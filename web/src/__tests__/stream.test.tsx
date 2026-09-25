import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { STREAM_OPENED, useStream, type StreamEvent } from "../api/client";
import { FakeEventSource } from "./fixtures/stream";

beforeEach(() => {
  FakeEventSource.install();
  vi.useFakeTimers();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function streamed() {
  const events: StreamEvent[] = [];
  const hook = renderHook(() => useStream((e) => events.push(e)));
  return { events, hook, kinds: () => events.map((e) => e.kind) };
}

describe("useStream - the node's live events", () => {
  it("passes each event on with its parsed body", () => {
    const { events } = streamed();
    act(() => FakeEventSource.latest().open());
    act(() => FakeEventSource.latest().emit("cdm.rejected", { code: "BAD_CHECKSUM", source: "upload" }));
    expect(events.at(-1)).toMatchObject({ kind: "cdm.rejected", data: { code: "BAD_CHECKSUM", source: "upload" } });
  });

  it("says it opened, so the console refetches what it missed while the stream was down", () => {
    const { hook, kinds } = streamed();
    act(() => FakeEventSource.latest().open());
    expect(kinds()).toEqual([STREAM_OPENED]);
    expect(hook.result.current.connected).toBe(true);

    act(() => FakeEventSource.latest().drop());
    expect(hook.result.current.connected).toBe(false);
    act(() => FakeEventSource.latest().open()); // the browser's own retry succeeded
    expect(kinds()).toEqual([STREAM_OPENED, STREAM_OPENED]);
    expect(hook.result.current.connected).toBe(true);
  });

  it("reconnects after an HTTP error, which the browser never retries (a proxy's 502 while the node restarts)", () => {
    const { hook, kinds } = streamed();
    act(() => FakeEventSource.latest().open());
    act(() => FakeEventSource.latest().fail());
    expect(hook.result.current.connected).toBe(false);
    expect(FakeEventSource.instances).toHaveLength(1);

    act(() => vi.advanceTimersByTime(3000));
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[0].readyState).toBe(FakeEventSource.CLOSED);

    act(() => FakeEventSource.latest().open());
    expect(hook.result.current.connected).toBe(true);
    expect(kinds()).toEqual([STREAM_OPENED, STREAM_OPENED]);
    act(() => FakeEventSource.latest().emit("link.state", { state: "DENIED" }));
    expect(kinds().at(-1)).toBe("link.state");
  });

  it("does not open a second stream while the browser is still retrying the first", () => {
    streamed();
    act(() => FakeEventSource.latest().drop());
    act(() => vi.advanceTimersByTime(10_000));
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("closes the stream and cancels a pending reconnect on unmount", () => {
    const { hook } = streamed();
    act(() => FakeEventSource.latest().fail());
    hook.unmount();
    act(() => vi.advanceTimersByTime(10_000));
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].readyState).toBe(FakeEventSource.CLOSED);
  });
});
