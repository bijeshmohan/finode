import { describe, expect, it } from "vitest";

import { cleanAmount, groupAmount, groupingFor, tidyAmount } from "./amount";

describe("cleanAmount keeps only what makes an amount", () => {
  it.each([
    ["12a.345", 2, "12.34"],
    ["42.00.00", 2, "42.00"],
    ["1.5", 0, "1"],
    ["1,500.00", 0, "1,500"],
    ["\u22121,234.50", 2, "-1,234.50"],
    ["-0012", 2, "-12"],
    ["1-2", 2, "12"],
    ["1,234.5", 2, "1,234.5"],
    ["00.5", 2, "0.5"],
  ] as const)("%s with %i places → %s", (text, places, expected) => {
    expect(cleanAmount(text, places)).toBe(expected);
  });
});

describe("tidyAmount writes it out whole", () => {
  it.each([
    ["1.", 2, "1.00"],
    ["1.1", 2, "1.10"],
    ["1,000", 0, "1000"],
    ["007.5", 2, "7.50"],
    ["-3", 2, "-3.00"],
    ["abc", 2, "abc"],
    ["", 2, ""],
  ] as const)("%s with %i places → %s", (text, places, expected) => {
    expect(tidyAmount(text, places)).toBe(expected);
  });
});

describe("groupAmount", () => {
  it("groups rupees in lakhs and crores", () => {
    expect(groupAmount("1234567.5", "indian")).toBe("12,34,567.5");
  });
  it("groups other currencies in thousands", () => {
    expect(groupAmount("1234567.5", "western")).toBe("1,234,567.5");
  });
  it("leaves what is not a number alone", () => {
    expect(groupAmount("x", "western")).toBe("x");
  });
  it("only rupees are indian", () => {
    expect(groupingFor("INR")).toBe("indian");
    expect(groupingFor("USD")).toBe("western");
    expect(groupingFor(null)).toBe("western");
  });
});
