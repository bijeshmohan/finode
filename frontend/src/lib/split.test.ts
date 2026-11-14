import { describe, expect, it } from "vitest";

import { allocation, differs, left, positive, sameAmount } from "./split";

describe("what is left to allocate on a side", () => {
  it("is the total less the rows that have an amount", () => {
    expect(left("1,000.00", ["600"], 2)).toBe("400.00");
    expect(left("12,34,567.89", ["34,567.89", ""], 2)).toBe("1200000.00");
  });

  it("can be over", () => {
    expect(allocation("1000", ["600", "600"], 2)).toEqual({ left: "-200.00", over: true, balanced: false });
    expect(allocation("1000", ["600", "400"], 2)).toEqual({ left: "0.00", over: false, balanced: true });
  });

  it("keeps the currency's places: yen have none", () => {
    expect(left("1000", ["333"], 0)).toBe("667");
  });

  it("counts an empty or unreadable amount as nothing", () => {
    expect(left("100", ["", "abc", "−"], 2)).toBe("100.00");
    expect(left("", ["30"], 2)).toBe("-30.00");
  });

  it("a row differs from the total only when the amounts differ", () => {
    expect(differs("1,000.00", "1000")).toBe(false);
    expect(differs("999.99", "1,000")).toBe(true);
    expect(differs("", "1000")).toBe(false);
  });
});

describe("comparing typed amounts", () => {
  it("reads grouping and decimals alike", () => {
    expect(sameAmount("1,000", "1000.00")).toBe(true);
    expect(sameAmount("", "")).toBe(true);
    expect(sameAmount("", "5")).toBe(false);
    expect(positive("0.00")).toBe(false);
    expect(positive("−5")).toBe(false);
    expect(positive("0.5")).toBe(true);
  });
});
