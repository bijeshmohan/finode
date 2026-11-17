// The Budgets views as the server answers them, for the tests.
import type { BudgetGroupView, BudgetRow, BudgetView } from "./queries";

export const ids = {
  rent: "00000000-0000-4000-8000-0000000000b1",
  food: "00000000-0000-4000-8000-0000000000b2",
  dining: "00000000-0000-4000-8000-0000000000b3",
  travel: "00000000-0000-4000-8000-0000000000b4",
};

export function row(over: Partial<BudgetRow> = {}): BudgetRow {
  return {
    category_id: ids.rent,
    name: "Rent",
    is_group: false,
    assigned: "500.00",
    activity: "0.00",
    available: "500.00",
    overspent_last_month: "0.00",
    of: "500.00",
    state: null,
    hint: "",
    percent: 0,
    over: false,
    group_name: null,
    unused: false,
    ...over,
  };
}

export function budget(over: Partial<BudgetView> = {}): BudgetView {
  return {
    month: "2026-11",
    is_current: true,
    pace: 43,
    ready_to_assign: "1000.00",
    sum: {
      money_in_accounts: "1500.00",
      reserved_for_cards: "0.00",
      available: "500.00",
      assigned_to_later_months: "0.00",
    },
    copyable: "0.00",
    show_intro: false,
    has_budget_accounts: true,
    overspent: "0.00",
    rows: [
      row(),
      row({
        category_id: ids.food,
        name: "Food",
        is_group: true,
        assigned: "0.00",
        available: "0.00",
        of: null,
        hint: "Dining · Groceries",
      }),
    ],
    unused_count: 0,
    ...over,
  };
}

export function group(over: Partial<BudgetGroupView> = {}): BudgetGroupView {
  return {
    id: ids.food,
    name: "Food",
    month: "2026-11",
    is_current: true,
    pace: 43,
    glance: { left: "500.00", spent: "0.00", of: "500.00", percent: 0, planned: true },
    assigned: "500.00",
    minimum: "500.00",
    kids: [row({ category_id: ids.dining, name: "Dining", group_name: "Food" })],
    ...over,
  };
}
