import { describe, expect, it } from "vitest";

import { amountOf, blankRow, datesFrom, removeRow, type RowState, settle, startRows } from "./rows";

const row = (over: Partial<RowState> = {}): RowState => ({ ...blankRow(), ...over });

describe("the rows of a side (recomputeTxn)", () => {
  it("one untouched row is the whole total", () => {
    const rows = settle([row({ choice: "food" })], "1,000", 2);
    expect(rows).toHaveLength(1);
    expect(amountOf(rows, 0, "1,000", 2)).toBe("1000.00");
  });

  it("typing less in a row adds an open row with what is left", () => {
    const rows = settle([row({ choice: "food", amount: "600", touched: true })], "1000", 2);
    expect(rows).toHaveLength(2);
    expect(amountOf(rows, 1, "1000", 2)).toBe("400.00");
    expect(rows[1]?.touched).toBe(false);
  });

  it("an open row goes once nothing is left, unless it has its account", () => {
    const full = [row({ choice: "food", amount: "1000", touched: true }), row()];
    expect(settle(full, "1000", 2)).toHaveLength(1);
    const chosen = [row({ choice: "food", amount: "1000", touched: true }), row({ choice: "rent" })];
    expect(settle(chosen, "1000", 2)).toHaveLength(2);
    expect(amountOf(settle(chosen, "1000", 2), 1, "1000", 2)).toBe("");
  });

  it("at most one open row without its account", () => {
    const rows = [row({ choice: "food", amount: "100", touched: true }), row(), row()];
    expect(settle(rows, "1000", 2)).toHaveLength(2);
  });

  it("yen keep no decimals", () => {
    const rows = settle([row({ choice: "food", amount: "333", touched: true })], "1000", 0);
    expect(amountOf(rows, 1, "1000", 0)).toBe("667");
  });

  it("removing a row brings back the remainder; the last row on a category side is the whole amount again", () => {
    const rows = [row({ choice: "food", amount: "600", touched: true }), row({ choice: "rent" })];
    const left = removeRow(rows, 1, true);
    expect(left).toHaveLength(1);
    expect(left[0]?.touched).toBe(false);
    expect(removeRow(rows, 1, false)[0]?.touched).toBe(true);
    const only = removeRow([row({ choice: "food", postedOn: "2026-11-20", amount: "5", touched: true })], 0, false);
    expect(only).toEqual([{ ...only[0], choice: null, category: null, postedOn: null, amount: "", touched: false }]);
  });

  it("an edit with several rows starts from their amounts; one row follows the total", () => {
    const line = (choice: string, amount: string) => ({ choice, amount, category_id: null, posted_on: null });
    const several = startRows([line("food", "600.00"), line("rent", "400.00")], "indian");
    expect(several.map((r) => [r.amount, r.touched])).toEqual([
      ["600.00", true],
      ["400.00", true],
    ]);
    expect(startRows([line("food", "1000.00")], "indian")[0]?.touched).toBe(false);
  });

  it("moving the entry past a posting date puts the line back on the entry's day", () => {
    const rows = [row({ postedOn: "2026-11-02" }), row({ postedOn: "2026-11-20" })];
    expect(datesFrom(rows, "2026-11-10").map((r) => r.postedOn)).toEqual([null, "2026-11-20"]);
  });
});
