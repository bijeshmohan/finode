import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, calledPaths, renderInApp, SIGNED_IN } from "../../test/render";
import { EntryScreen } from "./EntryScreen";
import { ids, view } from "./fixtures";
import type { EntryFormView } from "./queries";

const PEOPLE = [
  { id: ids.ada, name: "Ada" },
  { id: ids.bob, name: "Bob" },
];
const SAVED: Answers = { "/api/entries": [201, { transaction_id: "t1", recorded: "expense-shared" }] };

async function screenWith(form: EntryFormView = view({ people: PEOPLE }), answers: Answers = SAVED) {
  const rendered = renderInApp(<EntryScreen form={form} />, { ...SIGNED_IN, ...answers });
  await screen.findByLabelText("Amount");
  return rendered;
}

async function choose(side: string, label: string) {
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${side}`) }));
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(label) }));
}

async function addPeople(...names: string[]) {
  await userEvent.click(screen.getByRole("button", { name: "+ Add people" }));
  const sheet = await screen.findByRole("dialog", { name: "Split with" });
  for (const name of names) await userEvent.click(within(sheet).getByRole("button", { name }));
  await userEvent.click(within(sheet).getByRole("button", { name: /^Done/ }));
}

async function bodySent(fetch: ReturnType<typeof renderInApp>["fetch"]) {
  const call = fetch.mock.calls.find(([request]) => new URL(request.url).pathname === "/api/entries");
  if (!call) throw new Error("nothing was sent");
  return (await call[0].clone().json()) as Record<string, unknown>;
}

describe("Split: a bill shared with people", () => {
  it("the rows carry over into the editor", async () => {
    await screenWith();
    await userEvent.type(screen.getByLabelText("Amount"), "900");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await userEvent.click(screen.getByRole("radio", { name: "Split" }));
    expect(screen.getByRole("button", { name: /^You paid from/ })).toHaveTextContent("Bank");
    expect(screen.getByRole("button", { name: /^Category/ })).toHaveTextContent("Food");
    expect(screen.queryByRole("button", { name: /^Spent on/ })).not.toBeInTheDocument();
  });

  it("a removed person's values are not sent", async () => {
    const { fetch } = await screenWith();
    await userEvent.type(screen.getByLabelText("Amount"), "900");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await userEvent.click(screen.getByRole("radio", { name: "Split" }));
    await addPeople("Ada", "Bob");
    await userEvent.click(screen.getByRole("radio", { name: "Amounts" }));
    await userEvent.type(screen.getByLabelText("Your share value"), "300");
    await userEvent.type(screen.getByLabelText("Ada's share value"), "300");
    await userEvent.type(screen.getByLabelText("Bob's share value"), "300");
    await userEvent.click(screen.getByRole("button", { name: "Remove Bob" }));
    expect(screen.queryByLabelText("Bob's share value")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(calledPaths(fetch)).toContain("/api/entries");
    });
    expect(await bodySent(fetch)).toMatchObject({
      kind: "expense",
      total: "900.00",
      rows: [],
      share: {
        kind: "expense",
        category_id: ids.food,
        account_id: ids.bank,
        method: "exact",
        self_value: "300",
        self_paid: null,
        people: [{ contact_id: ids.ada, value: "300", paid: null }],
      },
    });
  });

  it("the preview shows the server's words", async () => {
    await screenWith(view({ people: PEOPLE }), {
      ...SAVED,
      "/api/views/entry-share-preview": [
        200,
        {
          kind: "expense",
          income: null,
          expense: {
            shares: [
              { name: "You", share_amount: "450.00" },
              { name: "Ada", share_amount: "450.00" },
            ],
            user_share: "450.00",
            owed: [{ contact_id: ids.ada, name: "Ada", direction: "receivable", amount: "450.00" }],
            unfunded: "0",
          },
        },
      ],
    });
    await userEvent.type(screen.getByLabelText("Amount"), "900");
    await userEvent.click(screen.getByRole("radio", { name: "Split" }));
    await addPeople("Ada");
    expect(await screen.findByText("Ada owes you", {}, { timeout: 2000 })).toBeInTheDocument();
    expect(screen.getByText("After this")).toBeInTheDocument();
  });

  it("a refused preview says why", async () => {
    await screenWith(view({ people: PEOPLE }), {
      ...SAVED,
      "/api/views/entry-share-preview": [400, { detail: "choose the account you paid from!" }],
    });
    await userEvent.type(screen.getByLabelText("Amount"), "900");
    await userEvent.click(screen.getByRole("radio", { name: "Split" }));
    await addPeople("Ada");
    expect(await screen.findByText("choose the account you paid from!", {}, { timeout: 2000 })).toBeInTheDocument();
  });

  it("a transfer goes back to Simple and Expense comes back with the people", async () => {
    await screenWith();
    await userEvent.click(screen.getByRole("radio", { name: "Split" }));
    await addPeople("Ada");
    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));
    expect(screen.queryByRole("radio", { name: "Split" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^From/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Expense" }));
    expect(screen.getByRole("radio", { name: "Simple" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "Split" }));
    expect(screen.getByRole("button", { name: "Remove Ada" })).toBeInTheDocument();
  });

  it("with no people it asks to add one", async () => {
    await screenWith(view());
    await userEvent.click(screen.getByRole("radio", { name: "Split" }));
    expect(screen.getByText("Add the people you share costs with first.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a person" })).toHaveAttribute("href", "/people/new");
  });

  it("an income's part that is theirs is sent", async () => {
    const { fetch } = await screenWith(view({ people: PEOPLE, kind: "income" }), {
      "/api/entries": [201, { transaction_id: "t1", recorded: "income-shared" }],
    });
    await userEvent.type(screen.getByLabelText("Amount"), "10000");
    await choose("Earned from", "Salary");
    await choose("Paid into", "Bank");
    await userEvent.click(screen.getByRole("radio", { name: "Split" }));
    expect(screen.getByRole("button", { name: /^Paid into/ })).toHaveTextContent("Bank");
    await addPeople("Ada");
    await userEvent.type(screen.getByLabelText("Ada's part"), "4000");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(calledPaths(fetch)).toContain("/api/entries");
    });
    expect(await bodySent(fetch)).toMatchObject({
      kind: "income",
      share: {
        kind: "income",
        category_id: ids.salary,
        account_id: ids.bank,
        people: [{ contact_id: ids.ada, theirs: "4000", received: null }],
      },
    });
  });
});
