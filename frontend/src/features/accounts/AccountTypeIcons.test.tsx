// Each account type's icon, as the server names it: the Accounts page's headings and cards, an account's own page and
// the new account form's kinds.
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp, SIGNED_IN } from "../../test/render";
import { account, accountForm, accounts, card, ids } from "./fixtures";

const PAGE = `/api/views/accounts/${ids.hdfc}`;
const drawn = (element: Element | null | undefined) =>
  element?.querySelector("svg[data-icon]")?.getAttribute("data-icon");

describe("account type icons", () => {
  it("lead each type's heading on the Accounts page, and not again on each of its rows", async () => {
    renderApp("/accounts", { ...SIGNED_IN, "/api/views/accounts": [200, accounts()] });
    const heading = await screen.findByRole("heading", { name: "Credit Card" });
    expect(drawn(heading.parentElement)).toBe("credit-card");
    expect(drawn(screen.getByRole("heading", { name: "Bank Account" }).parentElement)).toBe("landmark");
    expect(drawn(screen.getByRole("link", { name: /Visa/ }))).toBeUndefined();
    expect(drawn(screen.getByRole("link", { name: /HDFC/ }))).toBeUndefined();
  });

  it("lead each pinned row, where the types are mixed", async () => {
    const pinned = [card({ pinned: true }), card({ id: ids.visa, name: "Visa", icon: "credit-card", pinned: true })];
    renderApp("/accounts", { ...SIGNED_IN, "/api/views/accounts": [200, accounts({ pinned })] });
    const section = (await screen.findByRole("heading", { name: "Pinned" })).closest("section");
    if (!section) throw new Error("no section");
    expect(within(section).getAllByRole("link").map(drawn)).toEqual(["landmark", "credit-card"]);
  });

  it("sits beside an account's name on its page", async () => {
    renderApp(`/accounts/${ids.hdfc}`, { ...SIGNED_IN, [PAGE]: [200, account()] });
    const heading = await screen.findByRole("heading", { level: 1, name: "HDFC" });
    expect(drawn(heading.parentElement)).toBe("landmark");
  });

  it("is left out for an account with no type", async () => {
    renderApp(`/accounts/${ids.hdfc}`, { ...SIGNED_IN, [PAGE]: [200, account({ icon: null, badge: "system" })] });
    const heading = await screen.findByRole("heading", { level: 1, name: /HDFC/ });
    expect(drawn(heading.parentElement)).toBeUndefined();
  });

  it("show on each kind of the new account form", async () => {
    renderApp("/accounts/new", { ...SIGNED_IN, "/api/views/account-form": [200, accountForm()] });
    const kinds = await screen.findByRole("radiogroup", { name: "Kind of account" });
    expect(within(kinds).getAllByRole("radio").map(drawn)).toEqual(["landmark", "banknote", "credit-card", "wallet"]);
    expect(within(kinds).getByRole("radio", { name: "Credit Card" })).toBeInTheDocument();
  });
});
