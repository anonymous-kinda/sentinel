import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PcValue } from "../components/PcValue";
import type { Assessment } from "../api/types";

const base: Assessment = {
  method: "FOSTER_ESTES_2D",
  pc: 3.6e-5,
  pc_max: 2.0e-4,
  dilution_flag: false,
  dilution_margin: 0.3,
  miss_distance_m: 800,
  relative_speed_m_s: 14000,
  hbr_m: 20,
  inputs_hash: "abc",
  refusal_reason: null,
  diagnostics: {},
};

describe("PcValue - the Tier 6 contract in the UI", () => {
  it("renders a refusal as 'refused', never as a number or a zero", () => {
    render(<PcValue assessment={{ ...base, method: "REFUSED", pc: null, pc_max: null, refusal_reason: "NO_COVARIANCE" }} />);
    expect(screen.getByText(/refused/)).toBeTruthy();
    expect(screen.queryByText(/0/)).toBeNull();
  });

  it("always shows the worst case next to a diluted Pc", () => {
    render(<PcValue assessment={{ ...base, dilution_flag: true }} />);
    expect(screen.getByText(/worst case 2\.0×10⁻⁴/)).toBeTruthy();
  });

  it("does not claim a worst case when the Pc is not diluted", () => {
    render(<PcValue assessment={base} />);
    expect(screen.queryByText(/worst case/)).toBeNull();
    expect(screen.getByText("3.6×10⁻⁵")).toBeTruthy();
  });
});
