import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, calledPaths, renderInApp, SIGNED_IN } from "../../test/render";
import { EntryScreen } from "./EntryScreen";
import { ids, view } from "./fixtures";
import type { EntryFormView } from "./queries";

const SAVED: Answers = { "/api/entries": [201, { transaction_id: "t1", recorded: "transaction" }] };

async function screenWith(form: EntryFormView = view(), answers: Answers = SAVED, transactionId?: string) {
  const rendered = renderInApp(<EntryScreen form={form} {...(transactionId ? { transactionId } : {})} />, {
    ...SIGNED_IN,
    ...answers,
  });
  await screen.findByLabelText("Amount");
  return rendered;
}

async function choose(side: string, label: string) {
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${side}`) }));
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(label) }));
}

async function bodySent(fetch: ReturnType<typeof renderInApp>["fetch"]) {
  const call = fetch.mock.calls.find(([request]) => new URL(request.url).pathname.startsWith("/api/entries"));
  if (!call) throw new Error("nothing was sent");
  return (await call[0].clone().json()) as Record<string, unknown>;
}

describe("the Add screen", () => {
  it("saves an expense as the rows the person chose", async () => {
    const { fetch } = await screenWith();
    await userEvent.type(screen.getByLabelText("Amount"), "30");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(calledPaths(fetch)).toContain("/api/entries");
    });
    expect(await bodySent(fetch)).toMatchObject({
      kind: "expense",
      rows: [
        { choice: ids.bank, side: "credit", amount: "30.00" },
        { choice: ids.food, side: "debit", amount: "30.00" },
      ],
    });
  });

  it("tapping the chosen kind again offers every account", async () => {
    await screenWith();
    await userEvent.click(screen.getByRole("button", { name: "Expense" }));
    expect(screen.getByRole("button", { name: "Expense" })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: /^From/ }));
    expect(await screen.findByRole("heading", { name: "People" })).toBeInTheDocument();
  });

  it("a choice survives a kind that still offers it and goes with one that does not", async () => {
    await screenWith();
    await choose("Paid from", "Bank");
    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));
    expect(screen.getByRole("button", { name: /^From/ })).toHaveTextContent("Bank");
    await userEvent.click(screen.getByRole("button", { name: "Income" }));
    expect(screen.getByRole("button", { name: /^Earned from/ })).not.toHaveTextContent("Bank");
  });

  it("a transfer can swap its sides, an expense cannot", async () => {
    await screenWith();
    expect(screen.queryByRole("button", { name: "Swap From and To" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));
    await choose("From", "Bank");
    await userEvent.click(screen.getByRole("button", { name: "Swap From and To" }));
    expect(screen.getByRole("button", { name: /^To/ })).toHaveTextContent("Bank");
  });

  it("asks what a payment into a loan was for, and fills nothing in", async () => {
    const { fetch } = await screenWith();
    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));
    await userEvent.type(screen.getByLabelText("Amount"), "500");
    await choose("From", "Bank");
    await choose("To", "Home Loan");
    const category = screen.getByRole("button", { name: /^Category/ });
    expect(category).toHaveTextContent("No category");
    await userEvent.click(category);
    await userEvent.click(await screen.findByRole("button", { name: /EMI/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(async () => {
      expect(await bodySent(fetch)).toMatchObject({
        rows: [{ choice: ids.bank }, { choice: ids.loan, category_id: ids.emi }],
      });
    });
  });

  it("two quick taps on Save send one entry", async () => {
    const { fetch } = await screenWith(view(), { "/api/entries": "never" });
    await userEvent.type(screen.getByLabelText("Amount"), "30");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    const form = screen.getByRole("button", { name: "Save" }).closest("form");
    if (!form) throw new Error("no form");
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => {
      expect(calledPaths(fetch).filter((p) => p === "/api/entries")).toHaveLength(1);
    });
  });

  it("a refusal shows the server's words and keeps what was typed", async () => {
    await screenWith(view(), { "/api/entries": [400, { detail: "every posting needs an account!" }] });
    await userEvent.type(screen.getByLabelText("Amount"), "30");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("every posting needs an account!");
    expect(screen.getByLabelText("Amount")).toHaveValue("30.00"); // kept, and written out whole on leaving it
  });

  it("an edit starts from what was recorded and saves changes in place", async () => {
    const { fetch } = await screenWith(
      view({
        editing: true,
        total: "30.00",
        from_rows: [{ choice: ids.bank, amount: "30.00", category_id: null, posted_on: null }],
        to_rows: [{ choice: ids.food, amount: "30.00", category_id: null, posted_on: null }],
      }),
      { "/api/entries/t9": [200, { transaction_id: "t9", recorded: "transaction" }] },
      "t9",
    );
    expect(screen.getByLabelText("Amount")).toHaveValue("30.00");
    expect(screen.getByRole("button", { name: /^Paid from/ })).toHaveTextContent("Bank");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => {
      expect(calledPaths(fetch)).toContain("/api/entries/t9");
    });
  });

  it("an edit keeps each line's own posting date, as the web form does", async () => {
    const { fetch } = await screenWith(
      view({
        editing: true,
        total: "30.00",
        from_rows: [{ choice: ids.bank, amount: "30.00", category_id: null, posted_on: "2026-11-02" }],
        to_rows: [{ choice: ids.food, amount: "30.00", category_id: null, posted_on: null }],
      }),
      { "/api/entries/t9": [200, { transaction_id: "t9", recorded: "transaction" }] },
      "t9",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const rows = (await bodySent(fetch)).rows as { side: string; posted_on?: string | null }[];
    expect(rows.find((row) => row.side === "credit")?.posted_on).toBe("2026-11-02");
    expect(rows.find((row) => row.side === "debit")?.posted_on ?? null).toBeNull();
  });
});

function nth(found: HTMLElement[], index: number): HTMLElement {
  const element = found[index];
  if (!element) throw new Error(`no element ${String(index)}`);
  return element;
}

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };

async function settings(index: number, amount: string | null, date?: string) {
  await userEvent.click(nth(screen.getAllByRole("button", { name: "Amount and date" }), index));
  const sheet = await screen.findByRole("dialog");
  if (amount !== null) {
    const field = within(sheet).getByLabelText("Amount");
    await userEvent.clear(field);
    await userEvent.type(field, amount);
  }
  if (date !== undefined) fireEvent.change(within(sheet).getByLabelText("Date"), { target: { value: date } });
  await userEvent.click(within(sheet).getByRole("button", { name: "Done" }));
}

describe("several lines on a side", () => {
  it("typing less in a row adds a row with what is left", async () => {
    await screenWith(view(), { ...SAVED, ...INR });
    await userEvent.type(screen.getByLabelText("Amount"), "1000");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await settings(1, "600");
    const spent = screen.getAllByRole("button", { name: /^Spent on/ });
    expect(spent).toHaveLength(2);
    expect(spent[0]).toHaveTextContent("600.00");
    expect(spent[1]).toHaveTextContent("400.00 left");
  });

  it("removing a row brings the remainder back to one row", async () => {
    await screenWith(view(), { ...SAVED, ...INR });
    await userEvent.type(screen.getByLabelText("Amount"), "1000");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await settings(1, "600");
    await userEvent.click(nth(screen.getAllByRole("button", { name: "Amount and date" }), 1));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    const spent = screen.getAllByRole("button", { name: /^Spent on/ });
    expect(spent).toHaveLength(1);
    expect(spent[0]).not.toHaveTextContent("1,000.00");
  });

  it("several rows are sent, each with its amount and posting date", async () => {
    const { fetch } = await screenWith(view(), { ...SAVED, ...INR });
    await userEvent.type(screen.getByLabelText("Amount"), "1000");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await settings(1, "600");
    await userEvent.click(nth(screen.getAllByRole("button", { name: /^Spent on/ }), 1));
    await userEvent.click(await screen.findByRole("button", { name: /EMI/ }));
    await settings(0, null, "2026-11-20");
    expect(screen.getByRole("button", { name: /^Paid from/ })).toHaveTextContent("Posts 20 Nov");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await bodySent(fetch)).rows).toEqual([
      { choice: ids.bank, side: "credit", amount: "1000.00", category_id: null, posted_on: "2026-11-20" },
      { choice: ids.food, side: "debit", amount: "600.00", category_id: null, posted_on: null },
      { choice: ids.emi, side: "debit", amount: "400.00", category_id: null, posted_on: null },
    ]);
  });

  it("a side that does not add up says so; Save still sends it and shows the server's refusal", async () => {
    const { fetch } = await screenWith(view(), {
      ...INR,
      "/api/entries": [400, { detail: "debits (1,000.00) must equal credits (1,200.00)!" }],
    });
    await userEvent.type(screen.getByLabelText("Amount"), "1000");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await settings(0, "1200");
    expect(await screen.findByText("200.00 INR over")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("debits (1,000.00) must equal credits (1,200.00)!");
    expect(calledPaths(fetch)).toContain("/api/entries");
  });

  it("the date is asked only on an account, and Remove only when the side has several rows", async () => {
    await screenWith(view(), { ...SAVED, ...INR });
    await userEvent.type(screen.getByLabelText("Amount"), "1000");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await userEvent.click(nth(screen.getAllByRole("button", { name: "Amount and date" }), 0));
    let sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByLabelText("Date")).toHaveValue("2026-11-13");
    expect(within(sheet).queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole("button", { name: "Done" }));
    await userEvent.click(nth(screen.getAllByRole("button", { name: "Amount and date" }), 1));
    sheet = await screen.findByRole("dialog");
    expect(within(sheet).queryByLabelText("Date")).not.toBeInTheDocument();
  });
});
