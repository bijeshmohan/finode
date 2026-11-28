// The Accounts views as the server answers them, for the tests.
import type { components } from "../../api/schema";
import type { AccountCardData, AccountsView, AccountView } from "./queries";

export const ids = {
  banks: "00000000-0000-4000-8000-00000000ba01",
  hdfc: "00000000-0000-4000-8000-00000000ba02",
  old: "00000000-0000-4000-8000-00000000ba03",
  cards: "00000000-0000-4000-8000-00000000ca01",
  visa: "00000000-0000-4000-8000-00000000ca02",
};

export function card(over: Partial<AccountCardData> = {}): AccountCardData {
  return {
    id: ids.hdfc,
    name: "HDFC",
    balance: "5000.00",
    closed: false,
    pinned: false,
    note: null,
    icon: "landmark",
    ...over,
  };
}

export function accounts(over: Partial<AccountsView> = {}): AccountsView {
  return {
    account_count: 3,
    in_accounts: "5000.00",
    owed_on_cards: "300.00",
    pinned: [],
    kinds: [
      {
        name: "Bank Account",
        type: "assets.bank",
        icon: "landmark",
        total: "5000.00",
        owed: false,
        all_closed: false,
        add_url: "/accounts/new?type=assets.bank",
        cards: [card(), card({ id: ids.old, name: "Old Savings", balance: "0.00", closed: true })],
      },
      {
        name: "Credit Card",
        type: "liabilities.cards",
        icon: "credit-card",
        total: "300.00",
        owed: true,
        all_closed: false,
        add_url: "/accounts/new?type=liabilities.cards",
        cards: [
          card({
            id: ids.visa,
            name: "Visa",
            icon: "credit-card",
            balance: "300.00",
            note: { kind: "due", on: "2026-11-20", soon: true },
          }),
        ],
      },
    ],
    has_closed: true,
    ...over,
  };
}

export function account(over: Partial<AccountView> = {}): AccountView {
  return {
    id: ids.hdfc,
    name: "HDFC",
    icon: "landmark",
    details: null,
    badge: null,
    sub: "Bank Account",
    closed_on: null,
    balance: "5000.00",
    balance_after: null,
    direct: null,
    bill: null,
    bill_soon: false,
    can_set_days: false,
    is_group: false,
    has_children: false,
    cards: [],
    can_pin: true,
    pinned: false,
    can_edit: true,
    postable: true,
    new_transaction_url: `/transactions/new?account=${ids.hdfc}&back=/accounts/${ids.hdfc}`,
    upcoming: [],
    upcoming_total: null,
    entries: [],
    has_more: false,
    next_offset: 0,
    ...over,
  };
}

export function entry(id: string, over: Partial<AccountView["entries"][number]> = {}): AccountView["entries"][number] {
  return {
    id,
    date: "2026-11-12",
    title: "Swiggy",
    sub: "Food",
    posts_on: null,
    related: null,
    amount: "30.00",
    inflow: false,
    negative: false,
    balance: "4970.00",
    ...over,
  };
}

export const types: components["schemas"]["AccountTypeChoice"][] = [
  { key: "assets.bank", name: "Bank Account", icon: "landmark" },
  { key: "assets.cash", name: "Cash", icon: "banknote" },
  { key: "liabilities.cards", name: "Credit Card", icon: "credit-card" },
  { key: "assets.wallet", name: "Prepaid Wallet", icon: "wallet" },
];

export function accountForm(
  over: Partial<components["schemas"]["AccountFormView"]> = {},
): components["schemas"]["AccountFormView"] {
  return {
    editing: false,
    name: "",
    details: null,
    balance: null,
    type: null,
    types,
    statement_day: null,
    due_day: null,
    bill_rounding: "none",
    ...over,
  };
}
