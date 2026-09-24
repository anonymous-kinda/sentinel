import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "../features";
import { extensionTabs } from "../extensions";
import { NOW_MS, node } from "./fixtures/passes";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("feature tabs", () => {
  it("shows the Passes tab only on a node that runs the pass module", () => {
    expect(extensionTabs({ ...node, modules: ["passes"] }).map((t) => [t.id, t.label])).toEqual([["passes", "Passes"]]);
    expect(extensionTabs({ ...node, modules: ["sync", "ai"] }).map((t) => t.id)).not.toContain("passes");
  });

  it("renders the pass panel for the node", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    const [tab] = extensionTabs({ ...node, modules: ["passes"] });
    render(<>{tab.render({ node, version: 0, nowMs: NOW_MS, bump: () => {} })}</>);
    expect(screen.getByText(/Catalogued public imagers only/)).toBeTruthy();
  });
});
