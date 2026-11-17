import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import { accountForm, ids, kinds } from "./fixtures";

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
  it("asks about the budget and the bill by the kind chosen", async () => {
    open("/accounts/new", { [FORM]: [200, accountForm()] });
    await screen.findByRole("button", { name: "Banks" });
    expect(screen.queryByRole("checkbox", { name: /Part of the budget/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Banks" }));
    expect(screen.getByRole("button", { name: "Banks" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("checkbox", { name: /Part of the budget/ })).toBeChecked();
    expect(screen.getByLabelText("Current balance")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Statement day/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Loans" }));
    expect(screen.getByRole("checkbox", { name: /Part of the budget/ })).not.toBeChecked();
    expect(screen.getByLabelText("Amount you owe now")).toBeInTheDocument();
    expect(screen.getByLabelText(/Statement day/)).toBeInTheDocument();
  });

  it("adds the account and opens it", async () => {
    const { fetch, router } = open("/accounts/new", {
      [FORM]: [200, accountForm()],
      "/api/accounts/": [201, { id: NEW, name: "Car loan" }],
    });
    await userEvent.click(await screen.findByRole("button", { name: "Loans" }));
    await userEvent.type(screen.getByLabelText("Name"), "Car loan");
    await userEvent.type(screen.getByLabelText(/Statement day/), "10");
    await userEvent.type(screen.getByLabelText(/Payment due day/), "28");
    await userEvent.click(screen.getByRole("button", { name: "Add account" }));
    expect(await sent(fetch, "/api/accounts/", "POST")).toEqual({
      name: "Car loan",
      parent_id: kinds.loans.id,
      details: null,
      balance: "0",
      on_budget: false,
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
      "/api/accounts/": [400, { detail: "'Banks' already has an account called 'HDFC'!" }],
    });
    await userEvent.click(await screen.findByRole("button", { name: "Banks" }));
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
    parent_id: ids.banks,
    root_name: "Assets",
    can_budget: true,
    on_budget: true,
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
      "/api/views/accounts": [
        200,
        { net_worth: "0", account_count: 0, has_budget_accounts: false, pinned: [], kinds: [], has_closed: false },
      ],
    });
    await userEvent.click(await screen.findByRole("button", { name: "Delete account" }));
    expect(confirm).toHaveBeenCalledWith("Delete account 'HDFC'?");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/accounts");
    });
  });
});

describe("the group form", () => {
  it("asks what it holds, then makes it", async () => {
    const { fetch, router } = open("/accounts/new-group", {
      "/api/accounts/groups": [201, { id: NEW }],
      "/api/views/accounts": [
        200,
        { net_worth: "0", account_count: 0, has_budget_accounts: false, pinned: [], kinds: [], has_closed: false },
      ],
    });
    await userEvent.type(await screen.findByLabelText("Name"), "Family");
    await userEvent.click(screen.getByRole("button", { name: "Create group" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "choose whether it holds money you own or money you owe!",
    );
    await userEvent.click(screen.getByRole("radio", { name: "Money I own" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Part of the budget/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create group" }));
    expect(await sent(fetch, "/api/accounts/groups", "POST")).toEqual({
      name: "Family",
      root: "Assets",
      new_accounts_in_budget: true,
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/accounts");
    });
  });
});
