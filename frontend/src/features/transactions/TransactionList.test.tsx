import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderInApp } from "../../test/render";
import { row } from "./fixtures";
import { TransactionList } from "./TransactionList";

describe("TransactionList", () => {
  it("groups the rows by day, newest first, with the day's spending", async () => {
    renderInApp(
      <TransactionList
        rows={[
          row({ id: "a", title: "Swiggy", amount: "30.00" }),
          row({ id: "b", title: "Zomato", amount: "20.50" }),
          row({ id: "c", title: "DMart", date: "2026-11-12", amount: "10.00" }),
        ]}
        days={[{ date: "2026-11-13", spent: "50.50" }]}
        onOpen={vi.fn()}
      />,
    );
    const days = await screen.findAllByRole("heading", { level: 3 });
    expect(days.map((d) => d.textContent)).toEqual(["TodaySpent 50.50", "Yesterday"]);
  });

  it("shows money in with a plus and spending plain", async () => {
    renderInApp(
      <TransactionList
        rows={[
          row({ id: "a", title: "Salary", kind: "income", amount: "50000.00", sub: "Employer → Bank" }),
          row({ id: "b", title: "Rent", amount: "900.00" }),
        ]}
        onOpen={vi.fn()}
      />,
    );
    expect(await screen.findByText("+50,000.00")).toBeInTheDocument();
    expect(screen.getByText("900.00")).toBeInTheDocument();
  });

  it("folds several opening balances of one day into one row", async () => {
    const opening = { is_system: true, is_opening: true, kind: "transfer" as const };
    renderInApp(
      <TransactionList
        rows={[
          row({ id: "a", title: "Opening balance", sub: "Bank", ...opening }),
          row({ id: "b", title: "Opening balance", sub: "Card", ...opening }),
          row({ id: "c", title: "Swiggy" }),
        ]}
        onOpen={vi.fn()}
      />,
    );
    const fold = await screen.findByText("Opening balances");
    expect(within(fold.closest("details") ?? document.body).getByText("2 accounts")).toBeInTheDocument();
  });

  it("opens a row's sheet, and the pill opens the related entry instead", async () => {
    const onOpen = vi.fn();
    renderInApp(
      <TransactionList
        rows={[
          row({ id: "refund", title: "Refund", related: { id: "original", date: "2026-11-02", amount: "100.00" } }),
        ]}
        onOpen={onOpen}
      />,
    );
    await userEvent.click(await screen.findByRole("link", { name: /Related to an entry of 2 Nov/ }));
    expect(onOpen).toHaveBeenLastCalledWith("original");
    await userEvent.click(screen.getByRole("button", { name: /Refund/ }));
    expect(onOpen).toHaveBeenLastCalledWith("refund");
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("marks what a rule or an assistant added", async () => {
    renderInApp(
      <TransactionList
        rows={[row({ id: "a", recurring: true }), row({ id: "b", by_assistant: "Added by Claude" })]}
        onOpen={vi.fn()}
      />,
    );
    expect(await screen.findByText("Recurring")).toBeInTheDocument();
    expect(screen.getByText("Added by Claude")).toBeInTheDocument();
  });
});
