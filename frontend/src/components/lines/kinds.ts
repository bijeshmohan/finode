// What each kind of entry offers on each side and what the sides are called: an expense is paid from an
// account and spent on a category, income is earned from a category and paid into an account, a transfer moves between
// accounts and people, and "other" (the chosen kind tapped again) offers everything.
import type { PickGroup } from "./queries";

export type Kind = "expense" | "income" | "transfer" | "other";
export type Side = "credit" | "debit";

// The pickers' headings for the person's accounts: one per type (services/pickers.py), in the person's order.
export const ACCOUNT_GROUPS = ["Bank Account", "Cash", "Credit Card", "Prepaid Wallet"];
const ACCOUNTS = ACCOUNT_GROUPS;
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

/** A chosen category's icon (an account has none). */
export function iconOf(id: string | null, groups: PickGroup[]): string | null {
  return optionOf(id, groups)?.option.icon ?? null;
}

/** The name a row shows for its choice. */
export function labelOf(id: string | null, groups: PickGroup[]): string | null {
  return optionOf(id, groups)?.option.label ?? null;
}

/** Whether a choice is one of the person's accounts (not a category or a person): only an account posts on a day of
 * its own. */
export function isAccount(id: string | null, groups: PickGroup[]): boolean {
  const found = optionOf(id, groups);
  return found !== null && [...ACCOUNTS, "Equity"].includes(found.group);
}
