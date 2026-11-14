import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { calledPaths, renderApp, SIGNED_IN } from "../../test/render";
import { account, entry, ids } from "./fixtures";

const PAGE = `/api/views/accounts/${ids.hdfc}`;

describe("an account's page", () => {
  it("shows its name, kind, balance and entries with the running balance", async () => {
    renderApp(`/accounts/${ids.hdfc}`, {
      ...SIGNED_IN,
      [PAGE]: [
        200,
        account({ entries: [entry("t1"), entry("t2", { title: "Salary", inflow: true, balance: "5000.00" })] }),
      ],
    });
    expect(await screen.findByRole("heading", { level: 1, name: "HDFC" })).toBeInTheDocument();
    expect(screen.getByText("Banks")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Salary/ })).toHaveTextContent("+30.00");
    expect(screen.getByRole("button", { name: /Swiggy/ })).toHaveTextContent("4,970.00");
    // The back link and the tab bar both go to the Accounts page.
    expect(screen.getAllByRole("link", { name: "Accounts" }).every((l) => l.getAttribute("href") === "/accounts")).toBe(
      true,
    );
  });

  it("a card's bill offers to pay it", async () => {
    renderApp(`/accounts/${ids.visa}`, {
      ...SIGNED_IN,
      [`/api/views/accounts/${ids.visa}`]: [
        200,
        account({
          id: ids.visa,
          name: "Visa",
          bill: {
            account_id: ids.visa,
            statement_day: 1,
            due_day: 20,
            owed_total: "700.00",
            statement_due: "700.00",
            statement_date: "2026-11-01",
            due_date: "2026-11-20",
            next_statement_date: "2026-12-01",
            statement_balance: "700.00",
            paid_since: "0.00",
            spent_since: "0.00",
            rounded_by: "0.00",
            bill: "700.00",
            days_to_due: 7,
          },
        }),
      ],
    });
    expect(await screen.findByText("Due 20 Nov")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pay bill" })).toHaveAttribute(
      "href",
      `/transactions/new?pay=${ids.visa}&amount=700.00&back=/accounts/${ids.visa}`,
    );
  });

  it("the pin button pins it", async () => {
    const { fetch } = renderApp(`/accounts/${ids.hdfc}`, {
      ...SIGNED_IN,
      [PAGE]: [200, account()],
      [`/api/accounts/${ids.hdfc}`]: [200, {}],
    });
    await userEvent.click(await screen.findByRole("button", { name: "Pin to top" }));
    await waitFor(() => {
      expect(calledPaths(fetch)).toContain(`/api/accounts/${ids.hdfc}`);
    });
    expect(await screen.findByText("Pinned")).toBeInTheDocument();
  });

  it("closing asks first, then goes back to the Accounts page", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { router } = renderApp(`/accounts/${ids.hdfc}`, {
      ...SIGNED_IN,
      [PAGE]: [200, account({ balance: "0.00" })],
      [`/api/accounts/${ids.hdfc}/close`]: [200, {}],
      "/api/views/accounts": [
        200,
        { net_worth: "0", account_count: 0, has_budget_accounts: false, pinned: [], kinds: [], has_closed: false },
      ],
    });
    await userEvent.click(await screen.findByLabelText("More actions"));
    expect(screen.getByText(/Done with HDFC\? Closing it removes it from your lists and pickers/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close account" }));
    expect(confirm).toHaveBeenCalledWith("Close HDFC? You can reopen it later.");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/accounts");
    });
  });

  it("a refusal to close shows on the page", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderApp(`/accounts/${ids.hdfc}`, {
      ...SIGNED_IN,
      [PAGE]: [200, account()],
      [`/api/accounts/${ids.hdfc}/close`]: [400, { detail: "HDFC still holds 5,000.00: empty it first!" }],
    });
    await userEvent.click(await screen.findByLabelText("More actions"));
    expect(screen.getByText(/It has to be empty first: it still holds 5,000.00/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("empty it first!");
  });

  it("Load more appends the next chunk without repeating an entry", async () => {
    renderApp(`/accounts/${ids.hdfc}`, {
      ...SIGNED_IN,
      [PAGE]: (url) =>
        url.searchParams.get("offset") === "1"
          ? [200, account({ entries: [entry("t2", { title: "Rent" })], has_more: false, next_offset: 2 })]
          : [200, account({ entries: [entry("t1")], has_more: true, next_offset: 1 })],
    });
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("button", { name: /Rent/ })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Swiggy/ })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("an account with no entries offers to record one", async () => {
    renderApp(`/accounts/${ids.hdfc}`, { ...SIGNED_IN, [PAGE]: [200, account()] });
    expect(await screen.findByText("No transactions yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Record a transaction" })).toHaveAttribute(
      "href",
      `/transactions/new?account=${ids.hdfc}&back=/accounts/${ids.hdfc}`,
    );
  });

  it("an account that is not there says so", async () => {
    renderApp(`/accounts/${ids.hdfc}`, { ...SIGNED_IN, [PAGE]: [404, { detail: "account not found" }] });
    expect(await screen.findByRole("alert")).toHaveTextContent("account not found");
  });
});
