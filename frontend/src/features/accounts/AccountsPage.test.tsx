import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderApp, SIGNED_IN } from "../../test/render";
import type { AccountsView } from "./queries";
import { accounts, card, ids } from "./fixtures";

/** The section a heading heads. */
function sectionOf(heading: HTMLElement): HTMLElement {
  const found = heading.closest("section");
  if (!found) throw new Error("no section");
  return found;
}

const INR = { "/api/profile/": [200, { default_currency: "INR" }] as [number, unknown] };

describe("the Accounts page", () => {
  it("says how many accounts there are, with no net worth and no budget key", async () => {
    renderApp("/accounts", { ...SIGNED_IN, ...INR, "/api/views/accounts": [200, accounts()] });
    expect(await screen.findByRole("heading", { level: 1, name: "Accounts" })).toBeInTheDocument();
    expect(await screen.findByText("3 accounts")).toBeInTheDocument();
    expect(screen.queryByText("Net worth")).not.toBeInTheDocument();
    expect(screen.queryByText("in the budget")).not.toBeInTheDocument();
  });

  it("each type is a row of cards under its heading, in the order given, with its total and an add card", async () => {
    renderApp("/accounts", { ...SIGNED_IN, "/api/views/accounts": [200, accounts()] });
    const banks = sectionOf(await screen.findByRole("heading", { name: "Bank Account" }));
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Bank Account",
      "Credit Card",
    ]);
    expect(within(banks).getByText("5,000.00 · 1 account")).toBeInTheDocument();
    expect(within(banks).getByRole("link", { name: "Bank Account" })).toHaveAttribute("href", `/accounts/${ids.banks}`);
    expect(within(banks).getByRole("link", { name: /HDFC/ })).toHaveAttribute("href", `/accounts/${ids.hdfc}`);
    expect(within(banks).getByRole("link", { name: "Add account" })).toHaveAttribute(
      "href",
      "/accounts/new?type=assets.bank",
    );
    const cards = sectionOf(screen.getByRole("heading", { name: "Credit Card" }));
    expect(within(cards).getByText("300.00 owed · 1 account")).toBeInTheDocument();
    expect(within(cards).getByText("Bill due 20 Nov")).toBeInTheDocument();
  });

  it("closed accounts show only after Load more", async () => {
    renderApp("/accounts", { ...SIGNED_IN, "/api/views/accounts": [200, accounts()] });
    await screen.findByRole("heading", { name: "Bank Account" });
    expect(screen.queryByRole("link", { name: /Old Savings/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(screen.getByRole("link", { name: /Old Savings/ })).toHaveTextContent("closed");
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("a kind whose accounts are all closed hides until Load more", async () => {
    const view = accounts();
    const [first] = view.kinds as [AccountsView["kinds"][number]];
    const closedOnly = {
      ...first,
      name: "Prepaid Wallet",
      type: "assets.wallet" as const,
      all_closed: true,
      cards: [card({ name: "Paytm", closed: true })],
    };
    renderApp("/accounts", { ...SIGNED_IN, "/api/views/accounts": [200, { ...view, kinds: [closedOnly] }] });
    await screen.findByText("3 accounts");
    expect(screen.queryByRole("heading", { name: "Prepaid Wallet" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(screen.getByRole("heading", { name: "Prepaid Wallet" })).toBeInTheDocument();
  });

  it("pinned accounts come first, with no total and no add card", async () => {
    renderApp("/accounts", {
      ...SIGNED_IN,
      "/api/views/accounts": [200, accounts({ pinned: [card({ pinned: true })] })],
    });
    const pinned = sectionOf(await screen.findByRole("heading", { name: "Pinned" }));
    expect(within(pinned).getByText("1 account")).toBeInTheDocument();
    expect(within(pinned).queryByRole("link", { name: "Add account" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New group" })).not.toBeInTheDocument();
  });
});
