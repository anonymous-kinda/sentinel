import { vi } from "vitest";

/** A canned reply for one "METHOD path", or a request that never settles. */
export type Route = { status: number; body?: unknown } | "pending";

export const ok = (body: unknown): Route => ({ status: 200, body });

/** Stub `fetch` with a table of replies keyed "METHOD path". An unlisted
 *  request rejects, so a test never passes on a call it did not expect.
 *  `routes` stays live: change an entry to change the next reply. */
export function mockApi(routes: Record<string, Route>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(input)}`;
    const route = routes[key];
    if (!route) return Promise.reject(new Error(`unmocked ${key}`));
    if (route === "pending") return new Promise<Response>(() => {});
    const body = route.body === undefined ? null : JSON.stringify(route.body);
    return Promise.resolve(new Response(body, { status: route.status, headers: { "Content-Type": "application/json" } }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    fetchMock,
    routes,
    calls: (key: string) => fetchMock.mock.calls.filter(([input, init]) => `${init?.method ?? "GET"} ${String(input)}` === key),
  };
}
