import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ImagerCatalog } from "../components/passes/ImagerCatalog";
import { catalog } from "./fixtures/passes";

afterEach(cleanup);

describe("ImagerCatalog - what the model counts, and on what assumption", () => {
  it("lists every imager with sensor, field of regard, GSD, element age and the assumption's source", () => {
    render(<ImagerCatalog catalog={catalog} />);
    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    const wv3 = within(rows[0]);
    expect(wv3.getByText("WORLDVIEW-3 (WV-3)")).toBeTruthy();
    expect(wv3.getByText("EO")).toBeTruthy();
    expect(wv3.getByText("45.0°")).toBeTruthy();
    expect(wv3.getByText("0.31 m")).toBeTruthy();
    expect(wv3.getByText("0.5 d")).toBeTruthy();
    expect(wv3.getByText(catalog.imagers[0].basis)).toBeTruthy();
    expect(within(table).getByRole("columnheader", { name: /assumption source/i })).toBeTruthy();
  });

  it("flags a stale element set", () => {
    render(<ImagerCatalog catalog={catalog} />);
    const [, , sentinel2a] = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(within(sentinel2a).getByText("4.2 d")).toBeTruthy();
    expect(within(sentinel2a).getByText("STALE")).toBeTruthy();
    expect(within(screen.getAllByRole("row")[1]).queryByText("STALE")).toBeNull();
  });

  it("is collapsible, and says how many imagers it holds", () => {
    const { container } = render(<ImagerCatalog catalog={catalog} />);
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details?.open).toBe(false);
    expect(container.querySelector("summary")?.textContent).toMatch(/3 imagers/);
  });

  it("warns, outside the collapsed table, about every skipped imager and why", () => {
    const { container } = render(<ImagerCatalog catalog={catalog} />);
    const banner = screen.getByRole("note");
    expect(container.querySelector("details")?.contains(banner)).toBe(false);
    expect(banner.textContent).toContain("EX-IMAGER");
    expect(banner.textContent).toContain("no element set for this NORAD id");
  });

  it("shows no banner when nothing was skipped, and a dash for unknown values", () => {
    const imager = { ...catalog.imagers[0], gsd_m: null, element_epoch: null, element_age_days: null };
    render(<ImagerCatalog catalog={{ imagers: [imager], skipped: [] }} />);
    expect(screen.queryByRole("note")).toBeNull();
    const [row] = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(within(row).getAllByText("-")).toHaveLength(2);
  });
});
