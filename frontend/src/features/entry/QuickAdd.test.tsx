import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, renderInApp, SIGNED_IN } from "../../test/render";
import { EntryScreen } from "./EntryScreen";
import { ids, view } from "./fixtures";
import type { EntryFormView } from "./queries";

const NEW = "00000000-0000-4000-8000-0000000000n1";
const ROOTS = { assets: "00000000-0000-4000-8000-0000000000r1", equity: "00000000-0000-4000-8000-0000000000r3" };

const PARENTS: Partial<EntryFormView> = {
  account_parents: [
    { id: ROOTS.assets, name: "Assets", depth: 0, root: "Assets", opening_balance: true },
    { id: ids.bank, name: "Bank", depth: 1, root: "Assets", opening_balance: true },
    { id: ROOTS.equity, name: "Equity", depth: 0, root: "Equity", opening_balance: false },
  ],
  category_parents: [
    { id: ids.food, name: "Food", kind: "spending" },
    { id: ids.salary, name: "Salary", kind: "earning" },
  ],
};

async function screenWith(form: EntryFormView, answers: Answers) {
  const rendered = renderInApp(<EntryScreen form={form} />, {
    ...SIGNED_IN,
    "/api/entries": [201, { transaction_id: "t1", recorded: "transaction" }],
    ...answers,
  });
  await screen.findByLabelText("Amount");
  return rendered;
}

async function sent(fetch: ReturnType<typeof renderInApp>["fetch"], path: string) {
  await waitFor(() => {
    expect(fetch.mock.calls.some(([r]) => new URL(r.url).pathname === path)).toBe(true);
  });
  const call = fetch.mock.calls.find(([r]) => new URL(r.url).pathname === path);
  if (!call) throw new Error(`nothing sent to ${path}`);
  return (await call[0].clone().json()) as Record<string, unknown>;
}

async function openNew(side: string, noun: string) {
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${side}`) }));
  await userEvent.click(await screen.findByRole("button", { name: `＋ New ${noun}` }));
  return screen.findByRole("dialog", { name: `New ${noun}` });
}

describe("adding from the picker", () => {
  it("from an expense's To side it makes a spending category and chooses it", async () => {
    const { fetch } = await screenWith(view(PARENTS), { "/api/categories/": [201, { id: NEW, name: "Coffee" }] });
    await userEvent.type(screen.getByLabelText("Amount"), "30");
    const sheet = await openNew("Spent on", "category");
    expect(within(sheet).getByPlaceholderText("e.g. Pharmacy")).toBeInTheDocument();
    await userEvent.type(within(sheet).getByLabelText("Name"), "Coffee");
    await userEvent.selectOptions(within(sheet).getByLabelText("Under"), "Food");
    await userEvent.click(within(sheet).getByRole("button", { name: "Add category" }));
    expect(await sent(fetch, "/api/categories/")).toEqual({ name: "Coffee", kind: "spending", parent_id: ids.food });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "New category" })).not.toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole("button", { name: /^Paid from/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Bank/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await sent(fetch, "/api/entries")).rows).toContainEqual(
      expect.objectContaining({ choice: NEW, side: "debit" }),
    );
  });

  it("from an income's From side, an earning one", async () => {
    const { fetch } = await screenWith(view({ ...PARENTS, kind: "income" }), {
      "/api/categories/": [201, { id: NEW, name: "Freelance" }],
    });
    const sheet = await openNew("Earned from", "category");
    expect(within(sheet).getByPlaceholderText("e.g. Freelance")).toBeInTheDocument();
    expect(within(within(sheet).getByLabelText("Under")).queryByRole("option", { name: "Food" })).toBeNull();
    await userEvent.type(within(sheet).getByLabelText("Name"), "Freelance");
    await userEvent.click(within(sheet).getByRole("button", { name: "Add category" }));
    expect(await sent(fetch, "/api/categories/")).toEqual({ name: "Freelance", kind: "earning", parent_id: null });
  });

  it("an account under the chosen parent, with a balance only where it takes one", async () => {
    const { fetch } = await screenWith(view(PARENTS), { "/api/accounts/": [201, { id: NEW, name: "Kotak" }] });
    const sheet = await openNew("Paid from", "account");
    const under = within(sheet).getByLabelText("Belongs under");
    expect(under).toHaveValue(ROOTS.assets);
    expect(within(sheet).getByLabelText(/Current balance/)).toBeInTheDocument();
    await userEvent.selectOptions(under, ROOTS.equity);
    expect(within(sheet).queryByLabelText(/Current balance/)).not.toBeInTheDocument();
    await userEvent.selectOptions(under, ids.bank);
    await userEvent.type(within(sheet).getByLabelText("Name"), "Kotak");
    await userEvent.type(within(sheet).getByLabelText(/Current balance/), "500");
    await userEvent.click(within(sheet).getByRole("button", { name: "Add account" }));
    expect(await sent(fetch, "/api/accounts/")).toMatchObject({
      name: "Kotak",
      parent_id: ids.bank,
      balance: "500.00",
    });
  });

  it("a name already taken keeps the sheet open with the server's words", async () => {
    await screenWith(view(PARENTS), {
      "/api/accounts/": [400, { detail: "'Assets' already has an account called 'Bank'!" }],
    });
    const sheet = await openNew("Paid from", "account");
    await userEvent.type(within(sheet).getByLabelText("Name"), "Bank");
    await userEvent.click(within(sheet).getByRole("button", { name: "Add account" }));
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("already has an account called 'Bank'!");
    expect(screen.getByRole("dialog", { name: "New account" })).toBeInTheDocument();
  });

  it("Cancel keeps the row as it was", async () => {
    await screenWith(view(PARENTS), {});
    const sheet = await openNew("Paid from", "account");
    await userEvent.click(within(sheet).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "New account" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Paid from/ })).toHaveTextContent("Account…");
  });
});
