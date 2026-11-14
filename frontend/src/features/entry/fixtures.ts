// The Add screen's view as the server answers it, for the tests.
import type { EntryFormView, PickGroup } from "./queries";

export const ids = {
  bank: "00000000-0000-4000-8000-0000000000b1",
  card: "00000000-0000-4000-8000-0000000000c1",
  loan: "00000000-0000-4000-8000-0000000000l1",
  food: "00000000-0000-4000-8000-0000000000f1",
  salary: "00000000-0000-4000-8000-0000000000s1",
  emi: "00000000-0000-4000-8000-0000000000e1",
  ada: "00000000-0000-4000-8000-0000000000a1",
};

export const groups: PickGroup[] = [
  {
    title: "Assets",
    options: [{ id: ids.bank, label: "Bank", budget: true, balance: "5000.00" }],
  },
  {
    title: "Liabilities",
    options: [
      { id: ids.card, label: "Visa", budget: true, balance: "-200.00" },
      { id: ids.loan, label: "Home Loan", budget: false, balance: "-90000.00" },
    ],
  },
  { title: "People", options: [{ id: ids.ada, label: "Ada", budget: false, balance: "0.00" }] },
  { title: "Income", options: [{ id: ids.salary, label: "Salary", budget: false, balance: null }] },
  {
    title: "Expenses",
    options: [
      { id: ids.food, label: "Food", budget: false, balance: null },
      { id: ids.emi, label: "EMI", budget: false, balance: null },
    ],
  },
];

export function view(overrides: Partial<EntryFormView> = {}): EntryFormView {
  return {
    editing: false,
    kind: "expense",
    date: "2026-11-13",
    total: null,
    payee: "",
    payee_person: null,
    comment: "",
    tags: [],
    related: null,
    from_rows: [{ choice: null, amount: null, category_id: null, posted_on: null }],
    to_rows: [{ choice: null, amount: null, category_id: null, posted_on: null }],
    simple: true,
    person_page: null,
    groups,
    ...overrides,
  };
}
