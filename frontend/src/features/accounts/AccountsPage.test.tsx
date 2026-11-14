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
  it("says the net worth and how many accounts there are", async () => {
    renderApp("/accounts", { ...SIGNED_IN, ...INR, "/api/views/accounts": [200, accounts()] });
    expect(await screen.findByRole("heading", { level: 1, name: "Accounts" })).toBeInTheDocument();
    expect(await screen.findByText("Net worth")).toBeInTheDocument();
    expect(await screen.findByText("₹4,700.00")).toBeInTheDocument();
    expect(screen.getByText("3 accounts")).toBeInTheDocument();
    expect(screen.getByText("in the budget")).toBeInTheDocument();
  });

  it("each kind is a row of cards under its heading, with its total and an add card", async () => {
    renderApp("/accounts", { ...SIGNED_IN, "/api/views/accounts": [200, accounts()] });
    const banks = sectionOf(await screen.findByRole("heading", { name: "Banks" }));
    expect(within(banks).getByText("5,000.00 · 1 account")).toBeInTheDocument();
    expect(within(banks).getByRole("link", { name: "Banks" })).toHaveAttribute("href", `/accounts/${ids.banks}`);
    expect(within(banks).getByRole("link", { name: /HDFC/ })).toHaveAttribute("href", `/accounts/${ids.hdfc}`);
    expect(within(banks).getByRole("link", { name: "Add account" })).toHaveAttribute(
      "href",
      `/accounts/new?parent=${ids.banks}`,
    );
    const cards = sectionOf(screen.getByRole("heading", { name: "Credit Cards" }));
    expect(within(cards).getByText("300.00 owed · 1 account")).toBeInTheDocument();
    expect(within(cards).getByText("Bill due 20 Nov")).toBeInTheDocument();
  });

  it("closed accounts show only after Load more", async () => {
    renderApp("/accounts", { ...SIGNED_IN, "/api/views/accounts": [200, accounts()] });
    await screen.findByRole("heading", { name: "Banks" });
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
      name: "Food",
      group_id: null,
      all_closed: true,
      cards: [card({ name: "Snacks", closed: true })],
    };
    renderApp("/accounts", { ...SIGNED_IN, "/api/views/accounts": [200, { ...view, kinds: [closedOnly] }] });
    await screen.findByText("Net worth");
    expect(screen.queryByRole("heading", { name: "Food" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(screen.getByRole("heading", { name: "Food" })).toBeInTheDocument();
  });

  it("pinned accounts come first, with no total and no add card", async () => {
    renderApp("/accounts", {
      ...SIGNED_IN,
      "/api/views/accounts": [200, accounts({ pinned: [card({ pinned: true })] })],
    });
    const pinned = sectionOf(await screen.findByRole("heading", { name: "Pinned" }));
    expect(within(pinned).getByText("1 account")).toBeInTheDocument();
    expect(within(pinned).queryByRole("link", { name: "Add account" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New group" })).toHaveAttribute("href", "/accounts/new-group");
  });
});
