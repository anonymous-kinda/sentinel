import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { NextWindowCard } from "../components/passes/NextWindowCard";
import { NOW_MS, gaps, passes, skipped } from "./fixtures/passes";

afterEach(cleanup);

const text = () => document.body.textContent ?? "";

describe("NextWindowCard - the headline", () => {
  it("gives start and end as DTGs, the duration, a countdown and the reaction-time check", () => {
    render(<NextWindowCard view={passes} nowMs={NOW_MS} />);
    expect(screen.getByText("241130Z SEP 26")).toBeTruthy();
    expect(screen.getByText("241800Z SEP 26")).toBeTruthy();
    expect(screen.getByText("6h 31m")).toBeTruthy();
    expect(text()).toContain("opens T−20m 06s");
    expect(text()).toContain("meets the 30 min reaction time");
    expect(text()).toContain(passes.label);
    expect(text()).not.toMatch(/low confidence/i);
  });

  it("counts from now when the window is already open", () => {
    render(<NextWindowCard view={passes} nowMs={Date.parse("2026-09-24T17:40:00Z")} />);
    expect(text()).toContain("open now, closes T−20m 45s");
    expect(text()).toContain("shorter than the 30 min reaction time");
  });

  it("warns when a stale element set fed the window", () => {
    render(<NextWindowCard view={{ ...passes, next_unobserved: gaps[2] }} nowMs={NOW_MS} />);
    expect(text()).toMatch(/Low confidence/);
    expect(text()).toMatch(/older than 3 days/);
  });

  it("warns when catalogued imagers were skipped", () => {
    render(<NextWindowCard view={{ ...passes, catalog: { imagers: 38, skipped: [skipped] } }} nowMs={NOW_MS} />);
    expect(text()).toMatch(/Low confidence/);
    expect(text()).toMatch(/1 catalogued imager skipped/);
  });

  it("says plainly when there is no window long enough", () => {
    render(<NextWindowCard view={{ ...passes, next_unobserved: null }} nowMs={NOW_MS} />);
    expect(screen.getByText("No unobserved window of 30 min in the next 24 h")).toBeTruthy();
  });
});
