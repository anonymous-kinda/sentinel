import { afterEach, describe, expect, it, vi } from "vitest";
import { log } from "../lib/log";

afterEach(() => vi.restoreAllMocks());

describe("log - stable message, structured fields", () => {
  it("writes the message as the key and the fields beside it, never interpolated", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    log.error({ status: 403, error: "this node is read-only" }, "Pass unit save failed");
    expect(spy).toHaveBeenCalledWith("Pass unit save failed", { status: 403, error: "this node is read-only" });
  });

  it("has info and warn at the same shape", () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    log.info({ unit_id: "EX-UNIT-1" }, "Pass unit saved");
    log.warn({ skipped: 2 }, "Imagers skipped");
    expect(info).toHaveBeenCalledWith("Pass unit saved", { unit_id: "EX-UNIT-1" });
    expect(warn).toHaveBeenCalledWith("Imagers skipped", { skipped: 2 });
  });
});
