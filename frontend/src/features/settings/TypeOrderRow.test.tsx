import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";

const START = ["assets.bank", "assets.cash", "liabilities.cards", "assets.wallet"];
const profile = (order: string[]) => ({
  first_name: "Ada",
  last_name: null,
  default_currency: "INR",
  account_type_order: order,
});

function open(more: Answers) {
  return renderApp("/settings#account-types", {
    ...SIGNED_IN,
    "/api/profile/currencies": [200, [{ code: "INR", name: "Indian rupee", decimals: 2 }]],
    "/api/auth/options": [200, { signup_enabled: false, reset_enabled: false, test_notice: false }],
    ...more,
  });
}

function names(list: HTMLElement) {
  return within(list)
    .getAllByRole("listitem")
    .map((li) => li.querySelector("span")?.textContent);
}

describe("the order of the account types", () => {
  it("lists the four in the person's order, with up and down buttons where they can move", async () => {
    open({ "/api/profile/": [200, profile(START)] });
    const list = await screen.findByRole("list", { name: "Order of account types" });
    expect(names(list)).toEqual(["Bank Account", "Cash", "Credit Card", "Prepaid Wallet"]);
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((li) => li.querySelector("svg[data-icon]")?.getAttribute("data-icon")),
    ).toEqual(["landmark", "banknote", "credit-card", "wallet"]);
    expect(within(list).queryByRole("button", { name: "Move Bank Account up" })).not.toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "Move Bank Account down" })).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: "Move Prepaid Wallet up" })).toBeInTheDocument();
    expect(within(list).queryByRole("button", { name: "Move Prepaid Wallet down" })).not.toBeInTheDocument();
  });

  it("a move saves at once", async () => {
    let saved = START;
    const { fetch } = open({
      "/api/profile/": (_url: URL, request: Request) => {
        if (request.method === "PATCH") saved = ["assets.wallet", "assets.bank", "assets.cash", "liabilities.cards"];
        return [200, profile(saved)];
      },
    });
    const list = await screen.findByRole("list", { name: "Order of account types" });
    await userEvent.click(within(list).getByRole("button", { name: "Move Prepaid Wallet up" }));
    await waitFor(() => {
      expect(fetch.mock.calls.some(([r]) => r.method === "PATCH")).toBe(true);
    });
    const call = fetch.mock.calls.find(([r]) => r.method === "PATCH");
    expect(await call?.[0].clone().json()).toEqual({
      account_type_order: ["assets.bank", "assets.cash", "assets.wallet", "liabilities.cards"],
    });
  });

  it("a refusal shows the server's words and keeps the order", async () => {
    open({
      "/api/profile/": (_url: URL, request: Request) =>
        request.method === "PATCH" ? [422, { detail: "give each of the four types once!" }] : [200, profile(START)],
    });
    const list = await screen.findByRole("list", { name: "Order of account types" });
    await userEvent.click(within(list).getByRole("button", { name: "Move Cash up" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("give each of the four types once!");
    expect(names(list)).toEqual(["Bank Account", "Cash", "Credit Card", "Prepaid Wallet"]);
  });
});
