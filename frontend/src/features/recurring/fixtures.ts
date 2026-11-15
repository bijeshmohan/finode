// The Recurring views as the server answers them, for the tests.
import { groups, ids } from "../../components/lines/fixtures";
import type { RecurringFormView, RecurringView, RuleRow } from "./queries";

export const RULE = "00000000-0000-4000-8000-000000000301";

export function rule(over: Partial<RuleRow> = {}): RuleRow {
  return {
    id: RULE,
    title: "Landlord",
    amount: "1500.00",
    schedule: "Every month",
    status: "active",
    next_date: "2026-12-01",
    last_error: null,
    ...over,
  };
}

export function list(over: Partial<RecurringView> = {}): RecurringView {
  return { live: [rule()], stopped: [], ...over };
}

export function form(over: Partial<RecurringFormView> = {}): RecurringFormView {
  return {
    editing: false,
    kind: "expense",
    total: null,
    payee: "",
    comment: "",
    tags: [],
    from_rows: [{ choice: null, amount: null, category_id: null, posted_on: null }],
    to_rows: [{ choice: null, amount: null, category_id: null, posted_on: null }],
    groups: groups.filter((g) => g.title !== "People"),
    account_parents: [],
    category_parents: [],
    frequency: "monthly",
    every: 1,
    start_date: "2026-11-13",
    end_date: null,
    frequencies: [
      { value: "daily", name: "day" },
      { value: "weekly", name: "week" },
      { value: "monthly", name: "month" },
      { value: "yearly", name: "year" },
    ],
    status: null,
    schedule: null,
    active: null,
    next_date: null,
    last_date: null,
    skipped_date: null,
    last_error: null,
    ...over,
  };
}

/** A plain rule being edited: Bank pays Food 1,500 every month. */
export function editing(over: Partial<RecurringFormView> = {}): RecurringFormView {
  return form({
    editing: true,
    total: "1500.00",
    payee: "Landlord",
    from_rows: [{ choice: ids.bank, amount: "1500.00", category_id: null, posted_on: null }],
    to_rows: [{ choice: ids.food, amount: "1500.00", category_id: null, posted_on: null }],
    start_date: "2026-01-01",
    status: "active",
    schedule: "Every month",
    active: true,
    next_date: "2026-12-01",
    last_date: "2026-11-01",
    ...over,
  });
}
