import { describe, expect, it } from "vitest";

import { amountCases, moneyCases } from "./cases";
import { formatMoney, withCurrency } from "./money";

describe("formatMoney writes amounts as the server does", () => {
  it.each(moneyCases)("%s (%s) → %s", (value, grouping, expected) => {
    expect(formatMoney(value, grouping)).toBe(expected);
  });
});

describe("withCurrency puts the currency where the server does", () => {
  it.each(amountCases)("%s %s → %s", (text, code, expected) => {
    expect(withCurrency(text, code)).toBe(expected);
  });
});
