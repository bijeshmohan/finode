import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids } from "../../components/lines/fixtures";
import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import { editing, form, RULE } from "./fixtures";
import type { RecurringFormView } from "./queries";

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };

function openNew(view: RecurringFormView = form(), more: Answers = {}) {
  return renderApp("/recurring/new", {
    ...SIGNED_IN,
    ...INR,
    "/api/views/recurring-form": [200, view],
    "/api/views/recurring": "never",
    ...more,
  });
}

function openEdit(view: RecurringFormView = editing(), more: Answers = {}) {
  return renderApp(`/recurring/${RULE}/edit`, {
    ...SIGNED_IN,
    ...INR,
    "/api/views/recurring-form": [200, view],
    "/api/views/recurring": "never",
    ...more,
  });
}

async function choose(side: string, name: string) {
  await userEvent.click(screen.getByRole("button", { name: new RegExp(`^${side}`) }));
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(name) }));
}

async function bodySent(fetch: ReturnType<typeof renderApp>["fetch"], method: string) {
  await waitFor(() => {
    expect(fetch.mock.calls.some(([r]) => r.method === method)).toBe(true);
  });
  const call = fetch.mock.calls.find(([r]) => r.method === method);
  if (!call) throw new Error("nothing sent");
  const text = await call[0].clone().text();
  return { url: new URL(call[0].url).pathname, body: (text ? JSON.parse(text) : {}) as Record<string, unknown> };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a new recurring rule", () => {
  it("sends the rows, the schedule and the dates, then goes to the list", async () => {
    const { fetch, router } = openNew(form(), { "/api/recurring/form": [201, {}] });
    expect(await screen.findByRole("heading", { level: 1, name: "New recurring transaction" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Amount"), "1500");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await userEvent.type(screen.getByPlaceholderText("Payee or Merchant?"), "Landlord");
    await userEvent.clear(screen.getByLabelText("Every how many"));
    await userEvent.type(screen.getByLabelText("Every how many"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const sent = await bodySent(fetch, "POST");
    expect(sent.url).toBe("/api/recurring/form");
    expect(sent.body).toEqual({
      payee: "Landlord",
      comment: "",
      tags: [],
      rows: [
        { choice: ids.bank, side: "credit", amount: "1500.00", category_id: null, posted_on: null },
        { choice: ids.food, side: "debit", amount: "1500.00", category_id: null, posted_on: null },
      ],
      frequency: "monthly",
      every: 2,
      start_date: "2026-11-13",
      end_date: null,
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/recurring");
    });
    expect(
      await screen.findByText("Recurring transaction saved. Anything already due has been recorded."),
    ).toBeInTheDocument();
  });

  it("the unit follows the number", async () => {
    openNew();
    const unit = await screen.findByLabelText("Unit");
    expect(within(unit).getByRole("option", { name: "month" })).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Every how many"));
    await userEvent.type(screen.getByLabelText("Every how many"), "3");
    expect(within(unit).getByRole("option", { name: "months" })).toBeInTheDocument();
    expect(within(unit).getByRole("option", { name: "weeks" })).toBeInTheDocument();
  });

  it("the end date reads never until it is set, and clears", async () => {
    openNew();
    const ends = await screen.findByLabelText("Ends (optional)");
    expect(ends.closest("label")).toHaveTextContent("Endsnever");
    expect(screen.queryByRole("button", { name: "No end date" })).not.toBeInTheDocument();
    fireEvent.change(ends, { target: { value: "2027-06-30" } });
    expect(ends.closest("label")).toHaveTextContent("30 Jun 2027");
    await userEvent.click(screen.getByRole("button", { name: "No end date" }));
    expect(ends.closest("label")).toHaveTextContent("never");
  });

  it("a start in the past says it is recorded at once", async () => {
    openNew();
    const starts = await screen.findByLabelText("Starts");
    const hint = "A start date in the past is recorded right away for every missed date.";
    expect(screen.queryByText(hint)).not.toBeInTheDocument();
    fireEvent.change(starts, { target: { value: "2026-10-01" } });
    expect(screen.getByText(hint)).toBeInTheDocument();
  });

  it("a row's settings ask no posting day", async () => {
    openNew();
    await userEvent.type(await screen.findByLabelText("Amount"), "100");
    await choose("Paid from", "Bank");
    const [gear] = screen.getAllByRole("button", { name: "Amount and date" });
    if (!gear) throw new Error("no row settings");
    await userEvent.click(gear);
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).queryByLabelText("Date")).not.toBeInTheDocument();
  });

  it("shows a refusal above the button", async () => {
    openNew(form(), {
      "/api/recurring/form": [400, { detail: "choose where the money comes from and where it goes!" }],
    });
    await userEvent.type(await screen.findByLabelText("Amount"), "100");
    await choose("Paid from", "Bank");
    await choose("Spent on", "Food");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("choose where the money comes from");
  });
});

describe("editing a recurring rule", () => {
  it("starts from the rule and says where it stands", async () => {
    openEdit();
    expect(await screen.findByRole("heading", { level: 1, name: "Edit recurring transaction" })).toBeInTheDocument();
    expect(screen.getByLabelText("Amount")).toHaveValue("1,500.00");
    expect(screen.getByPlaceholderText("Payee or Merchant?")).toHaveValue("Landlord");
    expect(screen.getByText(/^Every month · next on Tue, 1 Dec/)).toHaveTextContent(
      "Every month · next on Tue, 1 Dec · last recorded Sun, 1 Nov",
    );
    expect(screen.getByRole("heading", { name: "Active" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument();
  });

  it("saves the changes to the rule", async () => {
    const { fetch } = openEdit(editing(), { [`/api/recurring/${RULE}/form`]: [200, {}] });
    await userEvent.click(await screen.findByRole("button", { name: "Save changes" }));
    const sent = await bodySent(fetch, "PUT");
    expect(sent.url).toBe(`/api/recurring/${RULE}/form`);
    expect(sent.body).toMatchObject({
      payee: "Landlord",
      start_date: "2026-01-01",
      rows: [
        { choice: ids.bank, side: "credit", amount: "1500.00" },
        { choice: ids.food, side: "debit", amount: "1500.00" },
      ],
    });
  });

  it("a rule that could not be recorded says so", async () => {
    openEdit(editing({ status: "error", last_error: "Bank can no longer be posted to" }));
    expect(await screen.findByText(/^Couldn't record Bank can no longer be posted to\./)).toHaveTextContent(
      "Couldn't record Bank can no longer be posted to. It will try again on the next run; fix the accounts or this rule.",
    );
  });

  it("pauses", async () => {
    const { fetch, router } = openEdit(editing(), { [`/api/recurring/${RULE}/pause`]: [200, {}] });
    expect(await screen.findByText("Pause it to stop recording without losing the rule.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect((await bodySent(fetch, "POST")).url).toBe(`/api/recurring/${RULE}/pause`);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/recurring");
    });
    expect(await screen.findByText("Paused. Nothing will be recorded until you resume it.")).toBeInTheDocument();
  });

  it("skips the next one after asking", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { fetch } = openEdit(editing(), { [`/api/recurring/${RULE}/skip`]: [200, {}] });
    expect(
      await screen.findByText("Just this once? Skip the next one (Tue, 1 Dec) and carry on after it."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Skip Tue, 1 Dec" }));
    expect(ask).toHaveBeenCalledWith("Skip 01 Dec 2026? Nothing will be recorded for it.");
    expect((await bodySent(fetch, "POST")).url).toBe(`/api/recurring/${RULE}/skip`);
  });

  it("a paused rule resumes", async () => {
    const { fetch } = openEdit(editing({ status: "paused", active: false }), {
      [`/api/recurring/${RULE}/resume`]: [200, {}],
    });
    expect(await screen.findByRole("heading", { name: "Paused" })).toBeInTheDocument();
    expect(screen.getByText(/^Every month · paused/)).toBeInTheDocument();
    expect(screen.getByText("Occurrences missed while paused are skipped.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect((await bodySent(fetch, "POST")).url).toBe(`/api/recurring/${RULE}/resume`);
  });

  it("an ended rule says how to carry on", async () => {
    openEdit(editing({ status: "ended", active: false }));
    expect(await screen.findByText("It has ended. Move the end date to carry on.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("deletes after asking", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { fetch, router } = openEdit(editing(), { [`/api/recurring/${RULE}`]: [204, null] });
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(ask).toHaveBeenCalledWith("Delete this recurring transaction? Transactions it already recorded are kept.");
    expect((await bodySent(fetch, "DELETE")).url).toBe(`/api/recurring/${RULE}`);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/recurring");
    });
  });

  it("goes back after deleting even when another view is slow to refresh", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let deleted = false;
    const { router } = renderApp(`/recurring/${RULE}/edit`, {
      ...SIGNED_IN,
      ...INR,
      "/api/views/recurring-form": () =>
        deleted ? [404, { detail: "recurring transaction not found" }] : [200, editing()],
      "/api/views/recurring": "never",
      "/api/views/todo": () =>
        new Promise((done) => {
          setTimeout(() => {
            done([200, { count: 0 }]);
          }, 150);
        }),
      [`/api/recurring/${RULE}`]: () => {
        deleted = true;
        return [204, null];
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(
      () => {
        expect(router.state.location.pathname).toBe("/recurring");
      },
      { timeout: 2000 },
    );
  });

  it("the old address of a rule opens its edit page", async () => {
    const { router } = renderApp(`/recurring/${RULE}`, {
      ...SIGNED_IN,
      "/api/views/recurring-form": [200, editing()],
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/recurring/${RULE}/edit`);
    });
  });
});
