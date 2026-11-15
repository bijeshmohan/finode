import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import { budget, ids, row } from "./fixtures";

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };
const NONE_COMING = {
  "/api/budget/coming-up": [200, { through: "2026-11-30", count: 0, total: null, items: [] }],
} as Answers;

function open(view = budget(), more: Answers = {}) {
  return renderApp("/budget", { ...SIGNED_IN, ...INR, ...NONE_COMING, "/api/views/budget": [200, view], ...more });
}

async function sent(fetch: ReturnType<typeof renderApp>["fetch"], path: string, method: string) {
  await waitFor(() => {
    expect(fetch.mock.calls.some(([r]) => new URL(r.url).pathname === path && r.method === method)).toBe(true);
  });
  const call = fetch.mock.calls.find(([r]) => new URL(r.url).pathname === path && r.method === method);
  if (!call) throw new Error("nothing sent");
  return (await call[0].clone().json()) as Record<string, unknown>;
}

describe("the Budgets head", () => {
  it("says what is ready to assign", async () => {
    open();
    expect(await screen.findByText("₹1,000.00")).toBeInTheDocument();
    expect(screen.getByText("Ready to assign")).toBeInTheDocument();
    expect(screen.getByText("Give it a job: tap a category")).toBeInTheDocument();
  });

  it("over-assigned shows zero and says so; zero says every rupee has a job; nothing says so", async () => {
    open(budget({ ready_to_assign: "-200.00" }));
    expect(await screen.findByText("Over-assigned by ₹200.00 · take some back from a category")).toBeInTheDocument();
    expect(screen.getByText("₹0.00")).toBeInTheDocument();
  });

  it("at zero every rupee has a job", async () => {
    open(budget({ ready_to_assign: "0.00" }));
    expect(await screen.findByText("Every ₹ has a job")).toBeInTheDocument();
  });

  it("with no categories there is nothing to assign yet", async () => {
    open(budget({ ready_to_assign: "0.00", rows: [] }));
    expect(await screen.findByText("Nothing to assign yet")).toBeInTheDocument();
    expect(screen.getByText("There are no expense categories yet.")).toBeInTheDocument();
  });

  it("the i shows the sum, and the payments coming up this month", async () => {
    open(budget(), {
      "/api/budget/coming-up": [200, { through: "2026-11-30", count: 2, total: "450.00", items: [] }],
    });
    await userEvent.click(await screen.findByLabelText("How what is ready to assign is worked out"));
    const panel = screen.getByRole("region", { name: "How this is worked out" });
    expect(within(panel).getByText("In your accounts")).toBeInTheDocument();
    expect(within(panel).getByText("Left in your categories")).toBeInTheDocument();
    const coming = await within(panel).findByRole("link", { name: /2 payments coming up by 30 Nov/ });
    expect(coming).toHaveAttribute("href", "/budget/coming-up");
    expect(coming).toHaveTextContent("450.00");
  });
});

describe("the Budgets list", () => {
  it("a row reads as the server says, and a group opens its page", async () => {
    open(
      budget({
        rows: [
          row({ state: "overspent", available: "-20.00", over: true, percent: 100, of: "100.00" }),
          row({ category_id: ids.food, name: "Food", is_group: true, of: null, hint: "Dining · Groceries" }),
        ],
      }),
    );
    expect(await screen.findByRole("button", { name: /Rent/ })).toHaveTextContent("of 100.00 · overspent");
    expect(screen.getByRole("link", { name: /Food/ })).toHaveAttribute(
      "href",
      `/budget/groups/${ids.food}?month=2026-11`,
    );
    expect(screen.getByRole("link", { name: /Food/ })).toHaveTextContent("nothing assigned · Dining · Groceries");
  });

  it("assigning sends the amount and closes the sheet", async () => {
    const { fetch } = open(budget(), { [`/api/budget/categories/${ids.rent}`]: [200, {}] });
    await userEvent.click(await screen.findByRole("button", { name: /Rent/ }));
    const sheet = await screen.findByRole("dialog", { name: "Rent" });
    const field = within(sheet).getByLabelText("Assigned this month");
    expect(field).toHaveValue("500.00");
    await userEvent.clear(field);
    await userEvent.type(field, "1200");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    expect(await sent(fetch, `/api/budget/categories/${ids.rent}`, "PUT")).toEqual({
      month: "2026-11-01",
      amount: "1200.00",
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Rent" })).not.toBeInTheDocument();
    });
  });

  it("a refusal stays in the sheet", async () => {
    open(budget(), { [`/api/budget/categories/${ids.rent}`]: [400, { detail: "too many decimals for INR" }] });
    await userEvent.click(await screen.findByRole("button", { name: /Rent/ }));
    const sheet = await screen.findByRole("dialog", { name: "Rent" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("too many decimals for INR");
    expect(screen.getByRole("dialog", { name: "Rent" })).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: "Move money" })).toHaveAttribute(
      "href",
      `/budget/move?month=2026-11&source=${ids.rent}`,
    );
  });

  it("copying last month sends the month", async () => {
    const { fetch } = open(budget({ copyable: "1200.00" }), { "/api/budget/copy": [200, {}] });
    await userEvent.click(await screen.findByRole("button", { name: "Copy last month's amounts · 1,200.00" }));
    expect(await sent(fetch, "/api/budget/copy", "POST")).toEqual({ month: "2026-11-01" });
  });

  it("unused groups are tucked away until Show", async () => {
    open(
      budget({
        rows: [row(), row({ category_id: ids.travel, name: "Travel", is_group: true, unused: true, of: null })],
        unused_count: 1,
      }),
    );
    await screen.findByRole("button", { name: /Rent/ });
    expect(screen.queryByRole("link", { name: /Travel/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "1 unused group hidden · Show" }));
    expect(screen.getByRole("link", { name: /Travel/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hide the 1 unused" }));
    expect(screen.queryByRole("link", { name: /Travel/ })).not.toBeInTheDocument();
  });

  it("the empty states, the intro and the overspent warning", async () => {
    open(budget({ has_budget_accounts: false, rows: [] }));
    expect(await screen.findByText(/No account is part of the budget yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose accounts" })).toHaveAttribute("href", "/accounts");
  });

  it("the intro and the overspent warning", async () => {
    open(budget({ show_intro: true, overspent: "50.00" }));
    expect(await screen.findByText("Give every ₹ a job")).toBeInTheDocument();
    expect(screen.getByText("Tap a category below to set aside your first amount.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Overspent by ₹50.00");
  });
});
