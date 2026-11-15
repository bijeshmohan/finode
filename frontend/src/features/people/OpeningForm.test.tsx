import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import { ids } from "./fixtures";
import type { OpeningFormView } from "./queries";

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };

function view(over: Partial<OpeningFormView> = {}): OpeningFormView {
  return {
    person_name: "Alice",
    editing: false,
    direction: "receivable",
    amount: null,
    date: "2026-11-13",
    description: "",
    paid: null,
    ...over,
  };
}

const EDITING = view({ editing: true, amount: "300.00", date: "2026-01-05", description: "From before" });

async function sent(fetch: ReturnType<typeof renderApp>["fetch"], method: string) {
  await waitFor(() => {
    expect(fetch.mock.calls.some(([r]) => r.method === method)).toBe(true);
  });
  const call = fetch.mock.calls.find(([r]) => r.method === method);
  if (!call) throw new Error("nothing sent");
  return { url: new URL(call[0].url).pathname, body: (await call[0].clone().json()) as Record<string, unknown> };
}

function open(path: string, form: OpeningFormView, more: Answers = {}) {
  return renderApp(path, {
    ...SIGNED_IN,
    ...INR,
    "/api/views/opening-form": [200, form],
    [`/api/views/people/${ids.alice}`]: "never",
    ...more,
  });
}

describe("an opening balance", () => {
  it("is added for the person and opens their page", async () => {
    const { fetch, router } = open(`/people/${ids.alice}/opening`, view(), {
      [`/api/contacts/${ids.alice}/opening-balance`]: [201, {}],
    });
    expect(await screen.findByRole("heading", { level: 1, name: "Opening balance" })).toBeInTheDocument();
    expect((await screen.findAllByRole("link", { name: "Alice" })).map((l) => l.getAttribute("href"))).toContain(
      `/people/${ids.alice}`,
    );
    expect(
      screen.getByText(
        "What Alice already owed before you started with finode. It touches none of your accounts or budgets.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Alice owes you" })).toBeChecked();
    await userEvent.type(screen.getByLabelText("Amount"), "120");
    await userEvent.type(screen.getByLabelText("Note (optional)"), "Old dinner");
    await userEvent.click(screen.getByRole("button", { name: "Add opening balance" }));
    const call = await sent(fetch, "POST");
    expect(call.url).toBe(`/api/contacts/${ids.alice}/opening-balance`);
    expect(call.body).toEqual({
      direction: "receivable",
      amount: "120.00",
      date: "2026-11-13",
      description: "Old dinner",
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/people/${ids.alice}`);
    });
    expect(await screen.findByText("Opening balance added")).toBeInTheDocument();
  });

  it("is edited with what changed", async () => {
    const { fetch } = open(`/people/${ids.alice}/opening/${ids.opening}/edit`, EDITING, {
      [`/api/transfers/${ids.opening}`]: [200, {}],
    });
    expect(await screen.findByRole("heading", { level: 1, name: "Edit opening balance" })).toBeInTheDocument();
    expect(screen.getByLabelText("Amount")).toHaveValue("300.00");
    expect(screen.getByLabelText("Note (optional)")).toHaveValue("From before");
    await userEvent.click(screen.getByRole("radio", { name: "You owe Alice" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const call = await sent(fetch, "PATCH");
    expect(call.url).toBe(`/api/transfers/${ids.opening}`);
    expect(call.body).toEqual({ direction: "payable" });
    expect(await screen.findByText("Opening balance saved")).toBeInTheDocument();
  });

  it("once part was paid back, who owes whom stays and the amount is held", async () => {
    const { fetch } = open(`/people/${ids.alice}/opening/${ids.opening}/edit`, view({ ...EDITING, paid: "100.00" }), {
      [`/api/transfers/${ids.opening}`]: [400, { detail: "the amount can't go below the 100.00 already paid back!" }],
    });
    expect(
      await screen.findByText(
        "100.00 of this has been paid back. The amount can't go below that, and who owes whom can't change.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Amount"));
    await userEvent.type(screen.getByLabelText("Amount"), "50");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect((await sent(fetch, "PATCH")).body).toEqual({ amount: "50.00" });
    expect(await screen.findByRole("alert")).toHaveTextContent("can't go below");
  });

  it("asks for the amount before sending", async () => {
    const { fetch } = open(`/people/${ids.alice}/opening`, view());
    await userEvent.click(await screen.findByRole("button", { name: "Add opening balance" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("enter the amount!");
    expect(fetch.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
  });
});
