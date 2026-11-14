import { fireEvent, screen, waitFor } from "@testing-library/react";
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
});
