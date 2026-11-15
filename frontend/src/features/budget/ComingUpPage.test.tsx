import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import type { ComingUpView } from "./queries";

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };
const RULE = "00000000-0000-4000-8000-000000000201";
const ENTRY = "00000000-0000-4000-8000-000000000202";
const PAY = "00000000-0000-4000-8000-000000000203";

function coming(over: Partial<ComingUpView> = {}): ComingUpView {
  return {
    through: "2026-11-30",
    count: 3,
    total: "1600.00",
    days: [
      {
        date: "2026-11-14",
        total: "1600.00",
        rows: [
          {
            title: "Landlord",
            sub: "Bank → Rent",
            amount: "1500.00",
            income: false,
            recurring_id: RULE,
            transaction_id: null,
          },
          {
            title: "Cab",
            sub: "Bank → Taxi",
            amount: "100.00",
            income: false,
            recurring_id: null,
            transaction_id: ENTRY,
          },
        ],
      },
      {
        date: "2026-11-20",
        total: null,
        rows: [
          {
            title: "Work",
            sub: "Salary → Bank",
            amount: "500.00",
            income: true,
            recurring_id: null,
            transaction_id: PAY,
          },
        ],
      },
    ],
    ...over,
  };
}

function open(view: ComingUpView) {
  return renderApp("/budget/coming-up", { ...SIGNED_IN, ...INR, "/api/views/coming-up": [200, view] });
}

describe("Coming up", () => {
  it("says until when, what it comes to and how many", async () => {
    open(coming());
    expect(await screen.findByRole("heading", { level: 1, name: "Coming up" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Budgets" }).map((l) => l.getAttribute("href"))).toContain("/budget");
    expect(await screen.findByText("Until Mon, 30 Nov")).toBeInTheDocument();
    expect(screen.getByText("3 payments that touch your budget accounts")).toBeInTheDocument();
    expect(screen.getByTestId("coming-figure")).toHaveTextContent("₹1,600.00");
  });

  it("one payment reads in the singular, and no total means no figure", async () => {
    open(coming({ count: 1, total: null }));
    expect(await screen.findByText("1 payment that touches your budget accounts")).toBeInTheDocument();
    expect(screen.queryByTestId("coming-figure")).not.toBeInTheDocument();
  });

  it("lists the days with their totals and the rows with their links", async () => {
    open(coming());
    const first = (await screen.findByText("Sat, 14 Nov")).closest("section");
    if (!first) throw new Error("no day");
    expect(within(first).getByText("1,600.00")).toBeInTheDocument();
    const rule = within(first).getByRole("link", { name: /Landlord/ });
    expect(rule).toHaveAttribute("href", `/recurring/${RULE}/edit`);
    expect(rule).toHaveTextContent("Repeats");
    expect(within(first).getByRole("link", { name: /Cab/ })).toHaveAttribute(
      "href",
      `/transactions/${ENTRY}/edit?back=/budget/coming-up`,
    );
    const later = screen.getByText("Fri, 20 Nov").closest("section");
    if (!later) throw new Error("no day");
    const pay = within(later).getByRole("link", { name: /Work/ });
    expect(pay).toHaveTextContent("+500.00");
    expect(pay).not.toHaveTextContent("Repeats");
  });

  it("says when nothing is coming up", async () => {
    open(coming({ count: 0, total: null, days: [] }));
    expect(await screen.findByText("Nothing is coming up before Mon, 30 Nov.")).toBeInTheDocument();
  });
});
