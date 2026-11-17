import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { details } from "./fixtures";

import { renderApp, SIGNED_IN } from "../../test/render";
import { row } from "./fixtures";
import type { TransactionsView } from "./queries";

function page(overrides: Partial<TransactionsView> = {}): TransactionsView {
  return {
    month: "2026-11",
    is_current: true,
    rows: [row()],
    days: [],
    total: 1,
    summary: null,
    upcoming: [],
    upcoming_total: null,
    error: null,
    applied: [],
    ...overrides,
  };
}

describe("the Transactions page", () => {
  it("says how many entries the month has", async () => {
    renderApp("/transactions", { ...SIGNED_IN, "/api/views/transactions": [200, page({ total: 3 })] });
    await waitFor(() => {
      expect(screen.getByTestId("summary")).toHaveTextContent("3 transactions");
    });
  });

  it("with a filter, says what the matches come to and offers to remove it", async () => {
    const { router } = renderApp("/transactions?month=2026-11&category=c1", {
      ...SIGNED_IN,
      "/api/views/transactions": [
        200,
        page({
          summary: { count: 2, total: "50.00", word: "spent" },
          applied: [{ key: "category", label: "Category", name: "Food" }],
        }),
      ],
    });
    await waitFor(() => {
      expect(screen.getByTestId("summary")).toHaveTextContent("2 transactions · 50.00 spent");
    });
    expect(screen.getByRole("button", { name: "Filter · 1" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Remove the category filter" }));
    expect(router.state.location.search).toBe("?month=2026-11");
  });

  it("show more adds the next page under the list", async () => {
    renderApp("/transactions", {
      ...SIGNED_IN,
      "/api/views/transactions": (url) =>
        url.searchParams.get("offset") === "1"
          ? [200, page({ rows: [row({ id: "b", title: "Zomato", date: "2026-11-12" })], total: 2 })]
          : [200, page({ rows: [row({ id: "a", title: "Swiggy" })], total: 2 })],
    });
    await userEvent.click(await screen.findByRole("button", { name: /Show 1 more/ }));
    expect(await screen.findByText("Zomato")).toBeInTheDocument();
    expect(screen.getByText("Swiggy")).toBeInTheDocument();
    expect(screen.getByText("That is all of November · 2 transactions")).toBeInTheDocument();
  });

  it("an empty month offers to record a transaction", async () => {
    renderApp("/transactions", { ...SIGNED_IN, "/api/views/transactions": [200, page({ rows: [], total: 0 })] });
    expect(await screen.findByText("No transactions yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Record a transaction" })).toHaveAttribute("href", "/transactions/new");
  });

  it("a search that finds nothing offers to show everything", async () => {
    renderApp("/transactions?q=zzz", { ...SIGNED_IN, "/api/views/transactions": [200, page({ rows: [], total: 0 })] });
    expect(await screen.findByText("Nothing matches.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Show everything" })).toHaveAttribute("href", "/transactions");
  });

  it("what is dated ahead waits in its own card", async () => {
    renderApp("/transactions", {
      ...SIGNED_IN,
      "/api/views/transactions": [
        200,
        page({
          upcoming: [
            { id: "u1", date: "2026-11-20", title: "Rent", sub: "Bank", amount: "900.00", income: false },
            { id: "u2", date: "2026-11-25", title: "Gym", sub: "Card", amount: "50.00", income: false },
          ],
          upcoming_total: "950.00",
        }),
      ],
    });
    expect(await screen.findByText("2 upcoming")).toBeInTheDocument();
    expect(screen.getByText("· 950.00 in all")).toBeInTheDocument();
  });

  it("a filter that does not parse is said above the list", async () => {
    renderApp("/transactions?account=nope", {
      ...SIGNED_IN,
      "/api/views/transactions": [
        200,
        page({ rows: [], total: 0, error: "Invalid filter: badly formed hexadecimal UUID string" }),
      ],
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid filter");
  });

  it("closing a sheet leaves no dead step in the history: Back goes where it went before", async () => {
    const { router } = renderApp("/transactions", {
      ...SIGNED_IN,
      "/api/views/transactions": [200, page()],
      [`/api/views/transactions/${row().id}`]: [200, details()],
    });
    await userEvent.click(await screen.findByRole("button", { name: /Swiggy/ }));
    await waitFor(() => {
      expect(router.state.location.search).toContain("open=");
    });
    // Escape, as a browser sends it to a modal dialog (jsdom does not; the browser tests press the real key).
    fireEvent(
      await screen.findByRole("dialog", { name: "Transaction details" }),
      new Event("cancel", { cancelable: true }),
    );
    await waitFor(() => {
      expect(router.state.location.search).not.toContain("open=");
    });
    expect(router.state.historyAction).toBe("POP");
  });

  it("a list that cannot be loaded says so and offers to try again", async () => {
    renderApp("/transactions", { ...SIGNED_IN, "/api/views/transactions": [500, { detail: "boom" }] });
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText("No transactions")).not.toBeInTheDocument();
  });

  it("while another month loads, the filters and the line above the list stay", async () => {
    const { router } = renderApp("/transactions?month=2026-11&category=c1", {
      ...SIGNED_IN,
      "/api/views/transactions": (url) =>
        url.searchParams.get("month") === "2026-10"
          ? "never"
          : [
              200,
              page({
                summary: { count: 2, total: "50.00", word: "spent" },
                applied: [{ key: "category", label: "Category", name: "Food" }],
              }),
            ],
    });
    await screen.findByRole("button", { name: "Filter · 1" });
    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));
    await userEvent.click(screen.getByRole("button", { name: "Filter · 1" }));
    await userEvent.click(screen.getByRole("button", { name: "Show transactions" }));
    expect(router.state.location.search).toContain("category=c1");
  });
});
