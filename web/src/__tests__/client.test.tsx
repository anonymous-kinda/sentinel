import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError, apiErrorMessage, deleteJSON, getJSON, putJSON, useResource } from "../api/client";
import { mockApi, ok } from "./fixtures/api";

function reply(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("HTTP errors carry their status and the server's reason", () => {
  it("getJSON rejects with the status code and the payload", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(409, { detail: "no unit set" })));
    const error = await getJSON("/api/passes?hours=24").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).status).toBe(409);
    expect(apiErrorMessage(error)).toBe("no unit set");
  });

  it("reads a validation error list as its messages", () => {
    const error = new HttpError("/api/passes/unit", 422, {
      detail: [{ loc: ["body", "lat_deg"], msg: "latitude must be within [-90, 90]" }, { msg: "unit_id is required" }],
    });
    expect(apiErrorMessage(error)).toBe("latitude must be within [-90, 90]; unit_id is required");
  });

  it("reads an object detail - {field, reason} or {code, reason} - as its reason, not as a bare status", () => {
    const unit = new HttpError("/api/passes/unit", 422, { detail: { field: "lat_deg", reason: "must be within -90 to 90" } });
    expect(apiErrorMessage(unit)).toBe("lat_deg: must be within -90 to 90");
    const screening = new HttpError("/api/screening", 409, { detail: { code: "NO_ELEMENTS", reason: "no element set for 99118" } });
    expect(apiErrorMessage(screening)).toBe("NO_ELEMENTS: no element set for 99118");
  });

  it("falls back to the error itself when the server gave no reason", () => {
    expect(apiErrorMessage(new HttpError("/api/x", 500, {}))).toBe("/api/x: HTTP 500");
    expect(apiErrorMessage(new TypeError("Failed to fetch"))).toBe("TypeError: Failed to fetch");
  });
});

describe("PUT and DELETE", () => {
  it("putJSON sends the body as JSON and returns the reply", async () => {
    const fetchMock = vi.fn(async () => reply(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(putJSON("/api/passes/unit", { unit_id: "EX-UNIT-1" })).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/passes/unit",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ unit_id: "EX-UNIT-1" }) }),
    );
  });

  it("deleteJSON accepts a 204 with no body", async () => {
    const fetchMock = vi.fn(async () => reply(204));
    vi.stubGlobal("fetch", fetchMock);
    await expect(deleteJSON("/api/passes/unit")).resolves.toBeDefined();
    expect(fetchMock).toHaveBeenCalledWith("/api/passes/unit", expect.objectContaining({ method: "DELETE" }));
  });

  it("rejects a 403 with the server's reason", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(403, { detail: "this node is read-only" })));
    const error = await deleteJSON("/api/passes/unit").catch((e: unknown) => e);
    expect((error as HttpError).status).toBe(403);
    expect(apiErrorMessage(error)).toBe("this node is read-only");
  });
});

describe("useResource", () => {
  it("never shows one path's data as another's: a new path starts empty, even when its fetch fails", async () => {
    const api = mockApi({
      "GET /api/events/A": ok({ event_id: "A" }),
      "GET /api/events/B": { status: 404, body: { detail: "no such event" } },
    });
    const { result, rerender } = renderHook(({ path }) => useResource<{ event_id: string }>(path), {
      initialProps: { path: "/api/events/A" },
    });
    await waitFor(() => expect(result.current.data).toEqual({ event_id: "A" }));

    rerender({ path: "/api/events/B" });
    expect(result.current.data).toBeNull();
    await waitFor(() => expect(result.current.status).toBe(404));
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("no such event");
    expect(api.calls("GET /api/events/B")).toHaveLength(1);
  });

  it("keeps the last good value of the same path while it refetches or after a failed refetch", async () => {
    const api = mockApi({ "GET /api/sync": ok({ role: "hub" }) });
    const { result, rerender } = renderHook(({ v }) => useResource<{ role: string }>("/api/sync", v), {
      initialProps: { v: 0 },
    });
    await waitFor(() => expect(result.current.data).toEqual({ role: "hub" }));
    api.routes["GET /api/sync"] = { status: 503, body: { detail: "busy" } };
    rerender({ v: 1 });
    await waitFor(() => expect(result.current.error).toBe("busy"));
    expect(result.current.data).toEqual({ role: "hub" });
  });

  it("drops what it held when the path goes away", async () => {
    mockApi({ "GET /api/events/A/trajectory": ok({ tca: "x" }) });
    const { result, rerender } = renderHook(({ path }: { path: string | null }) => useResource<{ tca: string }>(path), {
      initialProps: { path: "/api/events/A/trajectory" as string | null },
    });
    await waitFor(() => expect(result.current.data).toEqual({ tca: "x" }));
    rerender({ path: null });
    expect(result.current).toEqual({ data: null, error: null, status: null });
  });

  it("reports the status of a failed fetch and clears it on success", async () => {
    const fetchMock = vi.fn(async () => reply(404, { detail: "no unit set" }));
    vi.stubGlobal("fetch", fetchMock);
    const { result, rerender } = renderHook(({ v }) => useResource<{ unit_id: string }>("/api/passes/unit", v), {
      initialProps: { v: 0 },
    });
    await waitFor(() => expect(result.current.status).toBe(404));
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("no unit set");

    fetchMock.mockImplementation(async () => reply(200, { unit_id: "EX-UNIT-1" }));
    rerender({ v: 1 });
    await waitFor(() => expect(result.current.data).toEqual({ unit_id: "EX-UNIT-1" }));
    expect(result.current.status).toBeNull();
    expect(result.current.error).toBeNull();
  });
});
