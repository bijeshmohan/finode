import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import { accountForm, ids } from "./fixtures";

const NEW = "00000000-0000-4000-8000-0000000000ff";
const FORM = "/api/views/account-form";

async function sent(fetch: ReturnType<typeof renderApp>["fetch"], path: string, method: string) {
  await waitFor(() => {
    expect(fetch.mock.calls.some(([r]) => new URL(r.url).pathname === path && r.method === method)).toBe(true);
  });
  const call = fetch.mock.calls.find(([r]) => new URL(r.url).pathname === path && r.method === method);
  if (!call) throw new Error("nothing sent");
  return (await call[0].clone().json()) as Record<string, unknown>;
}

function open(path: string, answers: Answers) {
  return renderApp(path, { ...SIGNED_IN, ...answers });
}

describe("the new account form", () => {
  it("offers the four types and asks for a card's bill days only for a Credit Card", async () => {
    open("/accounts/new", { [FORM]: [200, accountForm()] });
    const kinds = await screen.findByRole("radiogroup", { name: "Kind of account" });
    expect(Array.from(kinds.querySelectorAll("button")).map((b) => b.textContent)).toEqual([
      "Bank Account",
      "Cash",
      "Credit Card",
      "Prepaid Wallet",
    ]);
    expect(screen.queryByRole("checkbox", { name: /Part of the budget/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Bank Account" }));
    expect(screen.getByRole("radio", { name: "Bank Account" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByLabelText("Current balance")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Statement day/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Credit Card" }));
    expect(screen.getByLabelText("Amount you owe now")).toBeInTheDocument();
    expect(screen.getByLabelText(/Statement day/)).toBeInTheDocument();
  });

  it("opened for a type, it starts on it", async () => {
    open("/accounts/new?type=assets.wallet", { [FORM]: [200, accountForm({ type: "assets.wallet" })] });
    expect(await screen.findByRole("radio", { name: "Prepaid Wallet" })).toHaveAttribute("aria-checked", "true");
  });

  it("adds the account and opens it", async () => {
    const { fetch, router } = open("/accounts/new", {
      [FORM]: [200, accountForm()],
      "/api/accounts/": [201, { id: NEW, name: "Amex" }],
    });
    await userEvent.click(await screen.findByRole("radio", { name: "Credit Card" }));
    await userEvent.type(screen.getByLabelText("Name"), "Amex");
    await userEvent.type(screen.getByLabelText(/Statement day/), "10");
    await userEvent.type(screen.getByLabelText(/Payment due day/), "28");
    await userEvent.click(screen.getByRole("button", { name: "Add account" }));
    expect(await sent(fetch, "/api/accounts/", "POST")).toEqual({
      name: "Amex",
      type: "liabilities.cards",
      details: null,
      balance: "0",
      statement_day: 10,
      due_day: 28,
      bill_rounding: "none",
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/accounts/${NEW}`);
    });
  });

  it("without a kind it asks for one and sends nothing", async () => {
    const { fetch } = open("/accounts/new", { [FORM]: [200, accountForm()] });
    await userEvent.type(await screen.findByLabelText("Name"), "Nowhere");
    await userEvent.click(screen.getByRole("button", { name: "Add account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("choose what kind of account it is!");
    expect(fetch.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
  });

  it("a refusal shows the server's words", async () => {
    open("/accounts/new", {
      [FORM]: [200, accountForm()],
      "/api/accounts/": [400, { detail: "'Bank Account' already has an account called 'HDFC'!" }],
    });
    await userEvent.click(await screen.findByRole("radio", { name: "Bank Account" }));
    await userEvent.type(screen.getByLabelText("Name"), "HDFC");
    await userEvent.click(screen.getByRole("button", { name: "Add account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already has an account called 'HDFC'!");
  });
});

describe("editing an account", () => {
  const editing = accountForm({
    editing: true,
    name: "HDFC",
    balance: "5000.00",
    type: "assets.bank",
    types: [],
  });
  const path = `/accounts/${ids.hdfc}/edit`;

  it("sends only what changed: a note leaves the balance alone", async () => {
    const { fetch } = open(path, { [FORM]: [200, editing], [`/api/accounts/${ids.hdfc}`]: [200, { id: ids.hdfc }] });
    await userEvent.click(await screen.findByText("+ Add a note"));
    await userEvent.type(screen.getByLabelText("Notes"), "Salary account");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await sent(fetch, `/api/accounts/${ids.hdfc}`, "PATCH")).toEqual({ details: "Salary account" });
  });

  it("sends nothing when nothing changed, and goes back to the account", async () => {
    const { fetch, router } = open(path, { [FORM]: [200, editing] });
    await userEvent.click(await screen.findByRole("button", { name: "Save changes" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/accounts/${ids.hdfc}`);
    });
    expect(fetch.mock.calls.some(([r]) => r.method === "PATCH")).toBe(false);
  });

  it("a changed balance is sent", async () => {
    const { fetch } = open(path, { [FORM]: [200, editing], [`/api/accounts/${ids.hdfc}`]: [200, { id: ids.hdfc }] });
    const balance = await screen.findByLabelText("Balance");
    await userEvent.clear(balance);
    await userEvent.type(balance, "5200");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await sent(fetch, `/api/accounts/${ids.hdfc}`, "PATCH")).toEqual({ balance: "5200.00" });
  });

  it("delete asks first and goes back to the Accounts page", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { router } = open(path, {
      [FORM]: [200, editing],
      [`/api/accounts/${ids.hdfc}`]: [204, null],
      "/api/views/accounts": [200, { account_count: 0, pinned: [], kinds: [], has_closed: false }],
    });
    await userEvent.click(await screen.findByRole("button", { name: "Delete account" }));
    expect(confirm).toHaveBeenCalledWith("Delete account 'HDFC'?");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/accounts");
    });
  });

  it("an account keeps its type: editing offers no kinds", async () => {
    open(path, { [FORM]: [200, editing] });
    await screen.findByRole("button", { name: "Save changes" });
    expect(screen.queryByRole("radiogroup", { name: "Kind of account" })).not.toBeInTheDocument();
  });
});
