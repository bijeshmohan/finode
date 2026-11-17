import { describe, expect, it } from "vitest";

import { groups, ids } from "./fixtures";
import { canSwap, KINDS, keepsChoice, offered, rowCategoryShown, screenOrder } from "./kinds";

const titles = (kind: Parameters<typeof offered>[0], side: "credit" | "debit") =>
  offered(kind, side, groups).map((g) => g.title);

describe("what each kind offers", () => {
  it("an expense is paid from accounts and spent on categories", () => {
    expect([KINDS.expense.credit.title, KINDS.expense.debit.title]).toEqual(["Paid from", "Spent on"]);
    expect(titles("expense", "credit")).toEqual(["Assets", "Liabilities"]);
    expect(titles("expense", "debit")).toEqual(["Expenses"]);
  });

  it("income is earned from categories and paid into accounts, the category last on screen", () => {
    expect([KINDS.income.credit.title, KINDS.income.debit.title]).toEqual(["Earned from", "Paid into"]);
    expect(titles("income", "credit")).toEqual(["Income"]);
    expect(screenOrder("income")).toEqual(["debit", "credit"]);
    expect(screenOrder("expense")).toEqual(["credit", "debit"]);
  });

  it("a transfer moves between accounts and people; other offers everything", () => {
    expect(titles("transfer", "debit")).toEqual(["Assets", "Liabilities", "People"]);
    expect(titles("other", "credit")).toEqual(groups.map((g) => g.title));
  });

  it("only a transfer or other can swap its sides", () => {
    expect([canSwap("expense"), canSwap("income"), canSwap("transfer"), canSwap("other")]).toEqual([
      false,
      false,
      true,
      true,
    ]);
  });

  it("a choice survives a kind that still offers it, and not one that does not", () => {
    expect(keepsChoice("transfer", "credit", ids.bank, groups)).toBe(true);
    expect(keepsChoice("income", "credit", ids.bank, groups)).toBe(false);
    expect(keepsChoice("income", "credit", null, groups)).toBe(true);
  });
});

describe("the category of a payment into a loan or fund", () => {
  it("shows only when money leaves the budget into an account outside it", () => {
    expect(rowCategoryShown(ids.loan, ids.bank, groups)).toBe(true);
    expect(rowCategoryShown(ids.bank, ids.loan, groups)).toBe(false);
    expect(rowCategoryShown(ids.card, ids.bank, groups)).toBe(false);
    expect(rowCategoryShown(ids.loan, null, groups)).toBe(false);
  });
});
