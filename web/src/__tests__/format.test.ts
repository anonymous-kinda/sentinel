import { describe, expect, it } from "vitest";
import { countdown, dtg, duration, sci, sciPlain } from "../lib/format";

describe("formatting", () => {
  it("writes probabilities in scientific notation with superscripts", () => {
    expect(sci(3.6e-5)).toBe("3.6×10⁻⁵");
    expect(sciPlain(1.234e-12, 3)).toBe("1.23e-12");
    expect(sci(0)).toBe("0");
  });
  it("counts down to the maneuver commit point", () => {
    expect(countdown(10 * 3600 + 32 * 60)).toBe("T−10h 32m");
    expect(countdown(-3 * 86400 - 5 * 3600)).toBe("+3d 05h");
  });
  it("formats military date-time groups in Zulu", () => {
    expect(dtg("2026-09-24T19:07:00Z")).toBe("241907Z SEP 26");
  });
  it("writes a length of time without a countdown sign", () => {
    expect(duration(5400)).toBe("1h 30m");
    expect(duration(45 * 60)).toBe("45m");
    expect(duration(26 * 3600 + 5 * 60)).toBe("26h 05m");
    expect(duration(0)).toBe("0m");
  });
});
