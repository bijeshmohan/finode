// The People views as the server answers them, for the tests.
import type { PeopleView, PersonEntryView, PersonView } from "./queries";

export const ids = {
  alice: "00000000-0000-4000-8000-000000000401",
  bob: "00000000-0000-4000-8000-000000000402",
  loan: "00000000-0000-4000-8000-000000000411",
  paid: "00000000-0000-4000-8000-000000000412",
  opening: "00000000-0000-4000-8000-000000000413",
};

export function people(over: Partial<PeopleView> = {}): PeopleView {
  return {
    show: "all",
    shows: [
      { key: "all", name: "All" },
      { key: "owed", name: "Owe you" },
      { key: "owe", name: "You owe" },
    ],
    has_archived: false,
    everyone: true,
    owed_total: "500.00",
    owe_total: "200.00",
    difference: "300.00",
    label: "Owed to you",
    rows: [
      { id: ids.alice, name: "Alice", sub: "Last 2 Nov", net: "500.00" },
      { id: ids.bob, name: "Bob", sub: "Last 3 Nov", net: "-200.00" },
    ],
    ...over,
  };
}

export function person(over: Partial<PersonView> = {}): PersonView {
  return {
    id: ids.alice,
    name: "Alice",
    phone: "99",
    email: "alice@example.com",
    notes: null,
    archived: false,
    receivable: "400.00",
    payable: "0.00",
    net: "400.00",
    open: [
      {
        transaction_id: ids.loan,
        name: "Loan",
        date: "2026-11-02",
        who: null,
        settled: "100.00",
        original: "500.00",
        outstanding: "400.00",
        receivable: true,
      },
    ],
    activity: [
      {
        transaction_id: ids.paid,
        title: "Paid back",
        date: "2026-11-05",
        sub: null,
        amount: "100.00",
        income: true,
      },
      {
        transaction_id: ids.loan,
        title: "Loan",
        date: "2026-11-02",
        sub: "Rent help",
        amount: "500.00",
        income: false,
      },
    ],
    more_activity: 0,
    ...over,
  };
}

export function entry(over: Partial<PersonEntryView> = {}): PersonEntryView {
  return {
    transaction_id: ids.loan,
    title: "Loan",
    date: "2026-11-02",
    amount: "500.00",
    notes: ["Rent help"],
    can_edit: false,
    can_reverse: true,
    ...over,
  };
}
