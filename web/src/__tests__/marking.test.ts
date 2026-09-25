import { describe, expect, it } from "vitest";
import { markingLevel } from "../lib/marking";

describe("markingLevel - the banner colour for a marking", () => {
  it.each([
    ["UNCLASSIFIED // EXERCISE", "unclassified"],
    ["unclassified//fouo", "unclassified"],
    ["CUI", "cui"],
    ["CONFIDENTIAL", "confidential"],
    ["SECRET//NOFORN", "secret"],
    ["TOP SECRET//SCI", "top-secret"],
    ["  TOP SECRET", "top-secret"],
  ])("reads %s as %s", (marking, level) => {
    expect(markingLevel(marking)).toBe(level);
  });

  it("does not read UNCLASSIFIED into a marking that only mentions it", () => {
    expect(markingLevel("SECRET (UNCLASSIFIED WHEN SEPARATED)")).toBe("secret");
  });

  it("calls anything else, or no marking at all, unknown", () => {
    expect(markingLevel(null)).toBe("unknown");
    expect(markingLevel("")).toBe("unknown");
    expect(markingLevel("EXERCISE")).toBe("unknown");
  });
});
