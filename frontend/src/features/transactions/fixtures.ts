// Rows and details as the view endpoints answer them, for the tests.
import type { Details, Row } from "./queries";

export function row(overrides: Partial<Row> = {}): Row {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    date: "2026-11-13",
    title: "Swiggy",
    sub: "Card → Food",
    amount: "597.00",
    kind: "expense",
    is_system: false,
    is_opening: false,
    related: null,
    recurring: false,
    by_assistant: null,
    ...overrides,
  };
}

export function details(overrides: Partial<Details> = {}): Details {
  return {
    row: row(),
    from_label: "Paid from",
    to_label: "Spent on",
    from_lines: [{ name: "Card", amount: "597.00", posted_on: null }],
    to_lines: [{ name: "Food", amount: "597.00", posted_on: null }],
    comment: null,
    tags: [],
    related_to: null,
    related: [],
    person: null,
    loan_like: false,
    with_names: [],
    source: null,
    source_url: null,
    external_id: null,
    added_by: null,
    changed_by: null,
    ...overrides,
  };
}
