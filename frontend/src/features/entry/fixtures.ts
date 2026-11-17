// The Add screen's view as the server answers it, for the tests.
import { groups, ids } from "../../components/lines/fixtures";
import type { EntryFormView } from "./queries";

export { groups, ids };

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
    mode: "simple",
    people: [],
    expense_share: {
      kind: "expense",
      category_id: null,
      account_id: null,
      method: "equal",
      self_value: null,
      self_paid: null,
      people: [],
    },
    income_share: { kind: "income", category_id: null, account_id: null, people: [] },
    person_page: null,
    groups,
    account_parents: [],
    category_parents: [],
    ...overrides,
  };
}
