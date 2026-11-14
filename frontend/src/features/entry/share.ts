// The Split of the Add screen as the person types it (people_editor.html, income_editor.html): amounts stay as typed
// strings, and what is sent is only what was typed for the people ticked. The server works out every share, what is
// owed and "you paid whatever the others did not" (services/entry_share.py).
import { type Grouping, groupAmount, tidyAmount } from "../../lib/amount";
import type { EntryBody, EntryFormView, PickGroup } from "./queries";

export type Method = "equal" | "exact" | "percentage" | "shares";

export interface ExpensePerson {
  contactId: string;
  value: string;
  paid: string;
}

export interface ExpenseShareState {
  categoryId: string | null;
  accountId: string | null;
  method: Method;
  selfValue: string;
  selfPaid: string;
  people: ExpensePerson[];
}

export interface IncomePerson {
  contactId: string;
  theirs: string;
  received: string;
}

export interface IncomeShareState {
  categoryId: string | null;
  accountId: string | null;
  people: IncomePerson[];
}

const typed = (value: string | null | undefined, grouping: Grouping) =>
  value === null || value === undefined ? "" : groupAmount(value, grouping);

export function startExpense(share: EntryFormView["expense_share"], grouping: Grouping): ExpenseShareState {
  return {
    categoryId: share.category_id ?? null,
    accountId: share.account_id ?? null,
    method: share.method,
    selfValue: typed(share.self_value, grouping),
    selfPaid: typed(share.self_paid, grouping),
    people: (share.people ?? []).map((p) => ({
      contactId: p.contact_id,
      value: typed(p.value, grouping),
      paid: typed(p.paid, grouping),
    })),
  };
}

export function startIncome(share: EntryFormView["income_share"], grouping: Grouping): IncomeShareState {
  return {
    categoryId: share.category_id ?? null,
    accountId: share.account_id ?? null,
    people: (share.people ?? []).map((p) => ({
      contactId: p.contact_id,
      theirs: typed(p.theirs, grouping),
      received: typed(p.received, grouping),
    })),
  };
}

/** A typed amount as sent: plain digits with the currency's decimals, or null when nothing was typed. */
function sent(text: string, places: number): string | null {
  const plain = tidyAmount(text.trim(), places).replace(/,/g, "");
  return plain === "" ? null : plain;
}

export function expenseBody(share: ExpenseShareState, places: number): NonNullable<EntryBody["share"]> {
  const valued = share.method !== "equal";
  return {
    kind: "expense",
    category_id: share.categoryId,
    account_id: share.accountId,
    method: share.method,
    self_value: valued ? sent(share.selfValue, places) : null,
    self_paid: sent(share.selfPaid, places),
    people: share.people.map((p) => ({
      contact_id: p.contactId,
      value: valued ? sent(p.value, places) : null,
      paid: sent(p.paid, places),
    })),
  };
}

export function incomeBody(share: IncomeShareState, places: number): NonNullable<EntryBody["share"]> {
  return {
    kind: "income",
    category_id: share.categoryId,
    account_id: share.accountId,
    people: share.people.map((p) => ({
      contact_id: p.contactId,
      theirs: sent(p.theirs, places),
      received: sent(p.received, places),
    })),
  };
}

function inGroups(id: string | null, groups: PickGroup[], titles: string[]): boolean {
  return id !== null && groups.some((g) => titles.includes(g.title) && g.options.some((o) => o.id === id));
}

const MONEY = ["Assets", "Liabilities"];

/** What the rows already say carries over to the Split, once (app.js CARRY): the account and the category, when the
 * Split has none yet. */
export function carryExpense(
  share: ExpenseShareState,
  paidFrom: string | null,
  spentOn: string | null,
  groups: PickGroup[],
): ExpenseShareState {
  return {
    ...share,
    accountId: share.accountId ?? (inGroups(paidFrom, groups, MONEY) ? paidFrom : null),
    categoryId: share.categoryId ?? (inGroups(spentOn, groups, ["Expenses"]) ? spentOn : null),
  };
}

export function carryIncome(
  share: IncomeShareState,
  earnedFrom: string | null,
  paidInto: string | null,
  groups: PickGroup[],
): IncomeShareState {
  return {
    ...share,
    accountId: share.accountId ?? (inGroups(paidInto, groups, MONEY) ? paidInto : null),
    categoryId: share.categoryId ?? (inGroups(earnedFrom, groups, ["Income"]) ? earnedFrom : null),
  };
}
