import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import { ids } from "./fixtures";

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };
const ALICE = {
  id: ids.alice,
  name: "Alice",
  phone: "99",
  email: null,
  notes: "From work",
  archived: false,
};

async function sent(fetch: ReturnType<typeof renderApp>["fetch"], method: string) {
  await waitFor(() => {
    expect(fetch.mock.calls.some(([r]) => r.method === method)).toBe(true);
  });
  const call = fetch.mock.calls.find(([r]) => r.method === method);
  if (!call) throw new Error("nothing sent");
  return { url: new URL(call[0].url).pathname, body: (await call[0].clone().json()) as Record<string, unknown> };
}

function openNew(more: Answers = {}) {
  return renderApp("/people/new", {
    ...SIGNED_IN,
    ...INR,
    "/api/contacts/": [201, { ...ALICE }],
    [`/api/views/people/${ids.alice}`]: "never",
    ...more,
  });
}

describe("adding a person", () => {
  it("sends the name and details and opens their page", async () => {
    const { fetch, router } = openNew();
    expect(await screen.findByRole("heading", { level: 1, name: "Add person" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "People" }).map((l) => l.getAttribute("href"))).toContain("/people");
    await userEvent.type(screen.getByLabelText("Name"), "Alice");
    await userEvent.type(screen.getByLabelText("Phone (optional)"), "99");
    await userEvent.click(screen.getByRole("button", { name: "Add person" }));
    expect((await sent(fetch, "POST")).body).toEqual({ name: "Alice", phone: "99", email: null, notes: null });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/people/${ids.alice}`);
    });
    expect(await screen.findByText("Person added")).toBeInTheDocument();
  });

  it("with what they already owe, sends the opening balance with them", async () => {
    const { fetch } = openNew();
    await userEvent.type(await screen.findByLabelText("Name"), "Alice");
    await userEvent.click(screen.getByRole("button", { name: "Already owes you, or is owed?" }));
    expect(
      screen.getByText(
        "Added to your opening balances. Your accounts and budgets don't change. It can be paid back with Settle up.",
      ),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "You owe them" }));
    await userEvent.type(screen.getByLabelText("Amount"), "250");
    fireEvent.change(screen.getByLabelText("Since"), { target: { value: "2026-01-05" } });
    await userEvent.click(screen.getByRole("button", { name: "Add person" }));
    expect((await sent(fetch, "POST")).body).toEqual({
      name: "Alice",
      phone: null,
      email: null,
      notes: null,
      opening: { direction: "payable", amount: "250.00", date: "2026-01-05", description: null },
    });
  });

  it("a refusal stays on the form and nobody is opened", async () => {
    const { router } = openNew({
      "/api/contacts/": [400, { detail: "INR amounts have at most 2 decimal places!" }],
    });
    await userEvent.type(await screen.findByLabelText("Name"), "Alice");
    await userEvent.click(screen.getByRole("button", { name: "Add person" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at most 2 decimal places");
    expect(router.state.location.pathname).toBe("/people/new");
  });
});

describe("editing a person", () => {
  it("starts from their details and sends what the fields say", async () => {
    const { fetch, router } = renderApp(`/people/${ids.alice}/edit`, {
      ...SIGNED_IN,
      [`/api/contacts/${ids.alice}`]: [200, ALICE],
      [`/api/views/people/${ids.alice}`]: "never",
    });
    expect(await screen.findByLabelText("Name")).toHaveValue("Alice");
    expect(screen.getByRole("heading", { level: 1, name: "Edit person" })).toBeInTheDocument();
    expect(screen.getByLabelText("Note (optional)")).toHaveValue("From work");
    expect(screen.queryByRole("button", { name: "Already owes you, or is owed?" })).not.toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Phone (optional)"));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const call = await sent(fetch, "PATCH");
    expect(call.url).toBe(`/api/contacts/${ids.alice}`);
    expect(call.body).toEqual({ name: "Alice", phone: null, email: null, notes: "From work" });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/people/${ids.alice}`);
    });
    expect(await screen.findByText("Person saved")).toBeInTheDocument();
  });
});
