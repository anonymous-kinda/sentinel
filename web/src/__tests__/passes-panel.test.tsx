import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NodeInfo } from "../api/types";
import { PassesPanel } from "../components/passes/PassesPanel";
import { mockApi, ok, type Route } from "./fixtures/api";
import { NOW_MS, catalog, node, passes, skipped, unit } from "./fixtures/passes";

const HONESTY =
  "Catalogued public imagers only. Uncatalogued and non-public sensors are outside this model. Fields of regard are " +
  "planning assumptions; element sets carry kilometre-level error, covered by the timing pad.";

const PASSES = "GET /api/passes?hours=24";
const UNIT = "GET /api/passes/unit";
const CATALOG = "GET /api/passes/catalog";

const healthy = () => ({ [UNIT]: ok(unit), [PASSES]: ok(passes), [CATALOG]: ok(catalog) });

function renderPanel(props: { node?: NodeInfo; version?: number } = {}) {
  const view = (p: typeof props) => <PassesPanel node={p.node ?? node} version={p.version ?? 0} nowMs={NOW_MS} />;
  const result = render(view(props));
  return { ...result, rerenderWith: (p: typeof props) => result.rerender(view(p)) };
}

beforeEach(() => {
  vi.spyOn(console, "info").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PassesPanel - the Passes tab", () => {
  it("shows that it is loading, with the honesty footer already visible", () => {
    mockApi({ [UNIT]: "pending", [PASSES]: "pending", [CATALOG]: "pending" });
    renderPanel();
    expect(screen.getAllByText(/Loading/).length).toBeGreaterThan(0);
    expect(screen.getByText(HONESTY)).toBeTruthy();
  });

  it("renders the headline, the timeline and the catalog when the node answers", async () => {
    mockApi(healthy());
    renderPanel();
    expect(await screen.findByText("241130Z SEP 26")).toBeTruthy();
    expect(screen.getByRole("group", { name: /Imaging passes over the unit/ })).toBeTruthy();
    expect(await screen.findByRole("table")).toBeTruthy();
    expect(screen.getByText("35.2600, -116.6800")).toBeTruthy();
    expect(screen.getByText(/skyfield-local/)).toBeTruthy();
    expect(screen.getByText(HONESTY)).toBeTruthy();
  });

  it("asks for a unit when none is set (409), and draws no timeline", async () => {
    mockApi({ [UNIT]: { status: 404, body: { detail: "no unit set" } }, [PASSES]: { status: 409, body: { detail: "no unit set" } }, [CATALOG]: ok(catalog) });
    renderPanel();
    expect(await screen.findByText(/No pass windows yet/)).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Set unit" })).toBeTruthy();
    expect(screen.queryByRole("group", { name: /Imaging passes/ })).toBeNull();
    expect(screen.queryByText(/unavailable/)).toBeNull();
    expect(screen.getByText(HONESTY)).toBeTruthy();
  });

  it("renders the server's error without blanking the tab", async () => {
    mockApi({ ...healthy(), [PASSES]: { status: 500, body: { detail: "element store unavailable" } } });
    renderPanel();
    expect(await screen.findByText(/Pass windows unavailable: element store unavailable/)).toBeTruthy();
    expect(await screen.findByText("EX-UNIT-1")).toBeTruthy();
    expect(screen.getByText(HONESTY)).toBeTruthy();
  });

  it("keeps the last good result on screen when a refetch fails", async () => {
    const api = mockApi(healthy());
    const { rerenderWith } = renderPanel();
    await screen.findByText("241130Z SEP 26");
    api.routes[PASSES] = { status: 503, body: { detail: "pass provider busy" } };
    rerenderWith({ version: 1 });
    expect(await screen.findByText(/pass provider busy/)).toBeTruthy();
    expect(screen.getByText(/Showing the last good result/)).toBeTruthy();
    expect(screen.getByText("241130Z SEP 26")).toBeTruthy();
  });

  it("refetches when the version bumps (SSE events)", async () => {
    const api = mockApi(healthy());
    const { rerenderWith } = renderPanel();
    await screen.findByText("241130Z SEP 26");
    const before = api.calls(PASSES).length;
    rerenderWith({ version: 1 });
    await waitFor(() => expect(api.calls(PASSES).length).toBe(before + 1));
    expect(api.calls(CATALOG).length).toBeGreaterThan(1);
  });

  it("saves the unit with PUT and refetches its windows", async () => {
    const api = mockApi({ ...healthy(), "PUT /api/passes/unit": ok(unit) });
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const before = api.calls(PASSES).length;
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.calls("PUT /api/passes/unit")).toHaveLength(1));
    expect(JSON.parse(String(api.calls("PUT /api/passes/unit")[0][1]?.body))).toEqual(unit);
    await waitFor(() => expect(api.calls(PASSES).length).toBe(before + 1));
  });

  it("deletes the unit with DELETE, then asks for one", async () => {
    const api = mockApi({ ...healthy(), "DELETE /api/passes/unit": { status: 204 } });
    renderPanel();
    await screen.findByText("241130Z SEP 26");
    // What the node will answer once the unit is gone.
    api.routes[UNIT] = { status: 404, body: { detail: "no unit set" } };
    api.routes[PASSES] = { status: 409, body: { detail: "no unit set" } };
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.calls("DELETE /api/passes/unit")).toHaveLength(1));
    expect(await screen.findByText(/No pass windows yet/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Set unit" })).toBeTruthy();
    expect(screen.queryByText("241130Z SEP 26")).toBeNull();
  });

  it("disables editing on a read-only node", async () => {
    mockApi(healthy());
    renderPanel({ node: { ...node, read_only: true } });
    expect(((await screen.findByRole("button", { name: "Edit" })) as HTMLButtonElement).disabled).toBe(true);
  });

  it("never uses the word 'safe', in any state", async () => {
    const states: Record<string, Route>[] = [
      { ...healthy(), [PASSES]: ok({ ...passes, catalog: { imagers: 38, skipped: [skipped] }, next_unobserved: passes.gaps[2] }) },
      { ...healthy(), [PASSES]: ok({ ...passes, next_unobserved: null }) },
      { [UNIT]: { status: 404, body: { detail: "no unit set" } }, [PASSES]: { status: 409, body: { detail: "no unit set" } }, [CATALOG]: ok(catalog) },
      { ...healthy(), [PASSES]: { status: 500, body: { detail: "element store unavailable" } } },
    ];
    for (const routes of states) {
      mockApi(routes);
      const { container, unmount } = renderPanel();
      await waitFor(() => expect(screen.queryByText(/Loading/)).toBeNull());
      const firstWindow = screen.queryAllByRole("img", { name: /rise/ })[0];
      if (firstWindow) fireEvent.focus(firstWindow);
      const edit = screen.queryByRole("button", { name: /Edit|Set unit/ });
      if (edit) fireEvent.click(edit);
      expect(container.innerHTML).not.toMatch(/safe/i);
      unmount();
    }
  });
});
