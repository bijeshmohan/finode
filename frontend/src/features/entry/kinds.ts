// What each kind of entry offers on each side and what the sides are called (app.js KINDS): an expense is paid from an
// account and spent on a category, income is earned from a category and paid into an account, a transfer moves between
// accounts and people, and "other" (the chosen kind tapped again) offers everything.
import type { PickGroup } from "./queries";

export type Kind = "expense" | "income" | "transfer" | "other";
export type Side = "credit" | "debit";

const ACCOUNTS = ["Assets", "Liabilities"];
const CATEGORIES = ["Expenses", "Income"];

export const KINDS: Record<Kind, Record<Side, { roots: string[] | null; title: string }>> = {
  expense: { credit: { roots: ACCOUNTS, title: "Paid from" }, debit: { roots: ["Expenses"], title: "Spent on" } },
  income: { credit: { roots: ["Income"], title: "Earned from" }, debit: { roots: ACCOUNTS, title: "Paid into" } },
  transfer: {
    credit: { roots: [...ACCOUNTS, "People"], title: "From" },
    debit: { roots: [...ACCOUNTS, "People"], title: "To" },
  },
  other: { credit: { roots: null, title: "From" }, debit: { roots: null, title: "To" } },
};

export function offered(kind: Kind, side: Side, groups: PickGroup[]): PickGroup[] {
  const roots = KINDS[kind][side].roots;
  return roots === null ? groups : groups.filter((g) => roots.includes(g.title));
}

export function keepsChoice(kind: Kind, side: Side, choice: string | null, groups: PickGroup[]): boolean {
  return choice === null || offered(kind, side, groups).some((g) => g.options.some((o) => o.id === choice));
}

export function isCategorySide(kind: Kind, side: Side): boolean {
  return (KINDS[kind][side].roots ?? []).some((root) => CATEGORIES.includes(root));
}

/** The order the sides show in: the category side comes after the account. */
export function screenOrder(kind: Kind): Side[] {
  return isCategorySide(kind, "credit") ? ["debit", "credit"] : ["credit", "debit"];
}

/** A category is never swapped with an account: only a transfer or "other" can swap its sides. */
export function canSwap(kind: Kind): boolean {
  return !isCategorySide(kind, "credit") && !isCategorySide(kind, "debit");
}

function optionOf(id: string | null, groups: PickGroup[]) {
  for (const group of groups) {
    const option = group.options.find((o) => o.id === id);
    if (option) return { group: group.title, option };
  }
  return null;
}

/** A payment from the budget into an account outside it (a loan, a fund) can say what it was for (syncRowCategories). */
export function rowCategoryShown(choice: string | null, other: string | null, groups: PickGroup[]): boolean {
  const mine = optionOf(choice, groups);
  const theirs = optionOf(other, groups);
  const outside = mine !== null && ACCOUNTS.includes(mine.group) && !mine.option.budget;
  const inBudget = theirs !== null && ACCOUNTS.includes(theirs.group) && theirs.option.budget;
  return outside && inBudget;
}

/** The name a row shows for its choice. */
export function labelOf(id: string | null, groups: PickGroup[]): string | null {
  return optionOf(id, groups)?.option.label ?? null;
}
