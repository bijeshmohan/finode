import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import type { TodoView } from "./queries";

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };
const IDS = {
  payment: "00000000-0000-4000-8000-000000000101",
  loan: "00000000-0000-4000-8000-000000000102",
  card: "00000000-0000-4000-8000-000000000103",
  rule: "00000000-0000-4000-8000-000000000104",
  emi: "00000000-0000-4000-8000-000000000105",
};

function todo(over: Partial<TodoView> = {}): TodoView {
  return {
    count: 4,
    uncategorised: [
      {
        transaction_id: IDS.payment,
        date: "2026-11-02",
        payee: "Bank EMI",
        account: "Liabilities:Home Loan",
        amount: "19277.00",
      },
    ],
    left_out_accounts: [{ account_id: IDS.loan, path: "Liabilities:Card", entries: 1, spent: "75.00" }],
    card_bills: [{ account_id: IDS.card, name: "Visa", bill: "1250.00", due_date: "2026-11-15", days_to_due: 2 }],
    failing_rules: [{ recurring_id: IDS.rule, name: "Rent", error: "Bank can no longer be posted to" }],
    categories: [{ id: IDS.emi, path: "Loans › EMI" }],
    ...over,
  };
}

const NOTHING = todo({ count: 0, uncategorised: [], left_out_accounts: [], card_bills: [], failing_rules: [] });

function open(view: TodoView, more: Answers = {}) {
  return renderApp("/accounts", {
    ...SIGNED_IN,
    ...INR,
    "/api/views/accounts": "never",
    "/api/views/todo": [200, view],
    ...more,
  });
}

async function bell() {
  const bar = await screen.findByRole("banner");
  return within(bar).getByRole("button", { name: "To do" });
}

describe("the to-do bell", () => {
  it("shows the count in the top bar and the sidebar", async () => {
    open(todo());
    const button = await bell();
    await waitFor(() => {
      expect(button).toHaveTextContent("4");
    });
    const side = screen.getByRole("navigation", { name: "Sidebar" });
    expect(within(side).getByRole("button", { name: /To do/ })).toHaveTextContent("4");
  });

  it("has no count when nothing needs you, and its sheet says so", async () => {
    open(NOTHING);
    const button = await bell();
    await waitFor(() => {
      expect(button).not.toHaveTextContent(/\d/);
    });
    await userEvent.click(button);
    const sheet = await screen.findByRole("dialog", { name: "To do" });
    expect(within(sheet).getByText("Nothing needs you.")).toBeInTheDocument();
  });

  it("lists each kind of item with its fix", async () => {
    open(todo());
    await userEvent.click(await bell());
    const sheet = await screen.findByRole("dialog", { name: "To do" });
    expect(within(sheet).getByText("1 payment has no category")).toBeInTheDocument();
    expect(within(sheet).getByText("The money left the budget and no category paid for it.")).toBeInTheDocument();
    expect(within(sheet).getByText(/Bank EMI/)).toHaveTextContent("Bank EMI · 2 Nov · 19,277.00");
    const select = within(sheet).getByRole("combobox", { name: "Category for Bank EMI" });
    expect(within(select).getByRole("option", { name: "Choose category…" })).toBeInTheDocument();
    expect(within(sheet).getByText("Liabilities:Card is not in the budget")).toBeInTheDocument();
    expect(within(sheet).getByText("₹75.00 spent this month in 1 entry is in no category.")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Add to budget" })).toBeInTheDocument();
    expect(within(sheet).getByText("Visa bill is due in 2 days")).toBeInTheDocument();
    expect(within(sheet).getByText("₹1,250.00 · due 15 Nov")).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: "Pay bill" })).toHaveAttribute(
      "href",
      `/transactions/new?pay=${IDS.card}&amount=1250.00&back=/accounts/${IDS.card}`,
    );
    expect(within(sheet).getByText("Rent could not be recorded")).toBeInTheDocument();
    expect(within(sheet).getByText("Bank can no longer be posted to")).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: "Open rule" })).toHaveAttribute(
      "href",
      `/recurring/${IDS.rule}/edit`,
    );
  });

  it("words bills that are due today or overdue, and several payments", async () => {
    const two = todo().uncategorised[0];
    if (!two) throw new Error("no fixture");
    open(
      todo({
        uncategorised: [two, { ...two, transaction_id: IDS.loan, payee: null }],
        card_bills: [
          { account_id: IDS.card, name: "Visa", bill: "1.00", due_date: "2026-11-13", days_to_due: 0 },
          { account_id: IDS.loan, name: "Amex", bill: "2.00", due_date: "2026-11-12", days_to_due: -1 },
          { account_id: IDS.rule, name: "Rupay", bill: "3.00", due_date: "2026-11-10", days_to_due: -3 },
          { account_id: IDS.emi, name: "Diners", bill: "4.00", due_date: "2026-11-14", days_to_due: 1 },
        ],
      }),
    );
    await userEvent.click(await bell());
    const sheet = await screen.findByRole("dialog", { name: "To do" });
    expect(within(sheet).getByText("2 payments have no category")).toBeInTheDocument();
    expect(within(sheet).getByRole("combobox", { name: "Category for Liabilities:Home Loan" })).toBeInTheDocument();
    expect(within(sheet).getByText("Visa bill is due today")).toBeInTheDocument();
    expect(within(sheet).getByText("Amex bill is overdue by 1 day")).toBeInTheDocument();
    expect(within(sheet).getByText("Rupay bill is overdue by 3 days")).toBeInTheDocument();
    expect(within(sheet).getByText("Diners bill is due in 1 day")).toBeInTheDocument();
  });

  it("gives a payment a category from the sheet and redraws it", async () => {
    let fixed = false;
    const { fetch } = open(todo(), {
      "/api/views/todo": () => [200, fixed ? NOTHING : todo()],
      [`/api/transactions/${IDS.payment}/category`]: () => {
        fixed = true;
        return [200, {}];
      },
    });
    await userEvent.click(await bell());
    const sheet = await screen.findByRole("dialog", { name: "To do" });
    await userEvent.selectOptions(within(sheet).getByRole("combobox", { name: "Category for Bank EMI" }), IDS.emi);
    await waitFor(() => {
      expect(within(sheet).getByText("Nothing needs you.")).toBeInTheDocument();
    });
    const call = fetch.mock.calls.find(([r]) => r.method === "POST");
    expect(await call?.[0].clone().json()).toEqual({ category_id: IDS.emi });
    expect(screen.getByRole("dialog", { name: "To do" })).toBeInTheDocument();
  });

  it("adds an account to the budget", async () => {
    const { fetch } = open(todo(), { [`/api/budget/accounts/${IDS.loan}/include`]: [200, {}] });
    await userEvent.click(await bell());
    const sheet = await screen.findByRole("dialog", { name: "To do" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Add to budget" }));
    await waitFor(() => {
      expect(
        fetch.mock.calls.some(([r]) => new URL(r.url).pathname === `/api/budget/accounts/${IDS.loan}/include`),
      ).toBe(true);
    });
  });

  it("shows a refusal in the sheet", async () => {
    open(todo(), {
      [`/api/transactions/${IDS.payment}/category`]: [
        400,
        { detail: "this entry has no payment waiting for a category!" },
      ],
    });
    await userEvent.click(await bell());
    const sheet = await screen.findByRole("dialog", { name: "To do" });
    await userEvent.selectOptions(within(sheet).getByRole("combobox", { name: "Category for Bank EMI" }), IDS.emi);
    expect(await within(sheet).findByRole("alert")).toHaveTextContent(/no payment waiting/);
  });

  it("closes when a link inside is followed", async () => {
    const { router } = open(todo(), { "/api/views/recurring-form": "never" });
    await userEvent.click(await bell());
    const sheet = await screen.findByRole("dialog", { name: "To do" });
    await userEvent.click(within(sheet).getByRole("link", { name: "Open rule" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/recurring/${IDS.rule}/edit`);
    });
    expect(screen.queryByRole("dialog", { name: "To do" })).not.toBeInTheDocument();
  });
});
