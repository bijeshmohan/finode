import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import { entry, ids, person } from "./fixtures";
import type { PersonEntryView, PersonView } from "./queries";

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };
const PATH = `/api/views/people/${ids.alice}`;

function open(view: PersonView = person(), more: Answers = {}) {
  return renderApp(`/people/${ids.alice}`, { ...SIGNED_IN, ...INR, [PATH]: [200, view], ...more });
}

async function menu() {
  await userEvent.click(await screen.findByLabelText("More actions"));
}

async function sheetOf(name: RegExp, sheet: PersonEntryView, more: Answers = {}) {
  const result = open(person(), { [`${PATH}/entries/${sheet.transaction_id}`]: [200, sheet], ...more });
  await userEvent.click(await screen.findByRole("button", { name }));
  return { ...result, dialog: await screen.findByRole("dialog", { name: sheet.title }) };
}

/** The tile under a section's head. */
async function tileAfter(heading: string): Promise<HTMLElement> {
  const tile = (await screen.findByRole("heading", { name: heading })).parentElement?.nextElementSibling;
  if (!(tile instanceof HTMLElement)) throw new Error(`no tile under ${heading}`);
  return tile;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a person's page", () => {
  it("says who owes whom, with their details and the way back", async () => {
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Alice" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "People" }).map((l) => l.getAttribute("href"))).toContain("/people");
    expect(screen.getByText("99 · alice@example.com")).toBeInTheDocument();
    expect(screen.getByText("Alice owes you")).toBeInTheDocument();
    expect(screen.getByTestId("person-figure")).toHaveTextContent("₹400.00");
  });

  it("reads you owe them, and all settled up", async () => {
    open(person({ net: "-150.00", receivable: "0.00", payable: "150.00" }));
    expect(await screen.findByText("You owe Alice")).toBeInTheDocument();
    expect(screen.getByTestId("person-figure")).toHaveTextContent("₹150.00");
  });

  it("all settled up", async () => {
    open(person({ net: "0.00", receivable: "0.00", payable: "0.00", open: [] }));
    expect(await screen.findByText("All settled up")).toBeInTheDocument();
  });

  it("offers the short-hands to the Add screen, Settle only while something is owed", async () => {
    open();
    const go = `&back=/people/${ids.alice}`;
    expect(await screen.findByRole("link", { name: "Expense" })).toHaveAttribute(
      "href",
      `/transactions/new?mode=split&with=${ids.alice}${go}`,
    );
    expect(screen.getByRole("link", { name: "Lend" })).toHaveAttribute(
      "href",
      `/transactions/new?move=lend&with=${ids.alice}${go}`,
    );
    expect(screen.getByRole("link", { name: "Borrow" })).toHaveAttribute(
      "href",
      `/transactions/new?move=borrow&with=${ids.alice}${go}`,
    );
    expect(screen.getByRole("link", { name: "Settle" })).toHaveAttribute(
      "href",
      `/transactions/new?move=settle&with=${ids.alice}${go}`,
    );
  });

  it("an archived person has no short-hands, and is restored from the menu", async () => {
    const { fetch } = open(person({ archived: true, net: "0.00", receivable: "0.00", payable: "0.00", open: [] }), {
      [`/api/contacts/${ids.alice}/restore`]: [200, {}],
    });
    expect(await screen.findByText("archived")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Lend" })).not.toBeInTheDocument();
    await menu();
    expect(screen.queryByRole("link", { name: "Add an opening balance" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restore Alice" }));
    await waitFor(() => {
      expect(fetch.mock.calls.some(([r]) => new URL(r.url).pathname === `/api/contacts/${ids.alice}/restore`)).toBe(
        true,
      );
    });
    expect(await screen.findByText("Person restored")).toBeInTheDocument();
  });

  it("the menu archives only when nothing is owed", async () => {
    open();
    await menu();
    expect(screen.getByRole("link", { name: "Edit" })).toHaveAttribute("href", `/people/${ids.alice}/edit`);
    expect(screen.getByRole("link", { name: "Add an opening balance" })).toHaveAttribute(
      "href",
      `/people/${ids.alice}/opening`,
    );
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
  });

  it("archives someone nothing is owed with", async () => {
    const { fetch } = open(person({ net: "0.00", receivable: "0.00", payable: "0.00", open: [] }), {
      [`/api/contacts/${ids.alice}/archive`]: [200, {}],
    });
    await menu();
    expect(
      screen.getByText("Archiving hides Alice from new entries. What you did together stays."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => {
      expect(fetch.mock.calls.some(([r]) => new URL(r.url).pathname === `/api/contacts/${ids.alice}/archive`)).toBe(
        true,
      );
    });
  });

  it("Remove archives someone with history, and deletes someone never dealt with", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { router } = open(person(), { [`/api/contacts/${ids.alice}`]: [200, { outcome: "archived" }] });
    await menu();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(ask).toHaveBeenCalledWith(
      "Remove Alice? Someone you never dealt with is deleted; otherwise they are archived.",
    );
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/people");
    });
    expect(await screen.findByText("Person archived. Their history stays.")).toBeInTheDocument();
  });

  it("a person removed for good is not kept to come back to", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { router, queryClient } = open(person(), { [`/api/contacts/${ids.alice}`]: [200, { outcome: "deleted" }] });
    await menu();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/people");
    });
    expect(await screen.findByText("Person removed")).toBeInTheDocument();
    await waitFor(() => {
      expect(queryClient.getQueryData(["views", "person", ids.alice])).toBeUndefined();
    });
    expect(router.state.historyAction).toBe("REPLACE");
  });

  it("a removal refused shows the server's words", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    open(person(), { [`/api/contacts/${ids.alice}`]: [400, { detail: "Alice still owes you 400.00!" }] });
    await menu();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Alice still owes you 400.00!");
  });

  it("lists what is open and what was done, each with its line", async () => {
    open();
    const open_ = await tileAfter("Open");
    expect(within(open_).getByRole("button", { name: /Loan/ })).toHaveTextContent("Mon, 2 Nov · 100.00 of 500.00 paid");
    expect(within(open_).getByText("400.00")).toHaveClass(/income/);
    const activity = await tileAfter("Activity");
    expect(within(activity).getByRole("button", { name: /Paid back/ })).toHaveTextContent("Thu, 5 Nov");
    expect(within(activity).getByText("100.00")).toHaveClass(/income/);
    expect(within(activity).getByRole("button", { name: /Loan/ })).toHaveTextContent("Mon, 2 Nov · Rent help");
  });

  it("an open row says which way when the person is owed both ways", async () => {
    open(
      person({
        open: [
          {
            transaction_id: ids.loan,
            name: "Loan",
            date: "2026-11-02",
            who: "they owe you",
            settled: null,
            original: "500.00",
            outstanding: "500.00",
            receivable: true,
          },
        ],
      }),
    );
    expect(await screen.findByRole("button", { name: /Loan.*they owe you/ })).toBeInTheDocument();
  });

  it("says when older entries are not shown, and when there is nothing yet", async () => {
    open(person({ more_activity: 1 }));
    expect(await screen.findByText("1 older entry not shown.")).toBeInTheDocument();
  });

  it("nothing yet", async () => {
    open(person({ activity: [], open: [] }));
    expect(await screen.findByText("Nothing yet with Alice.")).toBeInTheDocument();
  });
});

describe("an entry's sheet", () => {
  it("says what it was and reverses it after asking", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { dialog, fetch } = await sheetOf(/^Loan.*Rent help/, entry(), {
      [`/api/contacts/${ids.alice}/entries/${ids.loan}/reverse`]: [204, null],
    });
    expect(within(dialog).getByText("Mon, 2 Nov · Alice")).toBeInTheDocument();
    expect(within(dialog).getByText("500.00")).toBeInTheDocument();
    expect(within(dialog).getByText("Rent help")).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Reversing removes it for good, as if it had never happened. It can't be reversed while something has been paid back against it.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).queryByRole("link", { name: "Edit" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Reverse" }));
    expect(ask).toHaveBeenCalledWith("Reverse this? It is removed for good.");
    await waitFor(() => {
      expect(fetch.mock.calls.some(([r]) => r.method === "POST")).toBe(true);
    });
    expect(await screen.findByText("Reversed. It is as if it never happened.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Loan" })).not.toBeInTheDocument();
    });
  });

  it("a refusal stays in the sheet", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { dialog } = await sheetOf(/^Loan.*Rent help/, entry(), {
      [`/api/contacts/${ids.alice}/entries/${ids.loan}/reverse`]: [
        400,
        { detail: "something was settled against it: reverse the settlement first!" },
      ],
    });
    await userEvent.click(within(dialog).getByRole("button", { name: "Reverse" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("settled against it");
    expect(screen.getByRole("dialog", { name: "Loan" })).toBeInTheDocument();
  });

  it("an opening balance can be edited, an evened-out entry cannot be reversed", async () => {
    const { dialog } = await sheetOf(
      /^Loan.*Rent help/,
      entry({ title: "Opening balance", can_edit: true, notes: [] }),
    );
    expect(within(dialog).getByRole("link", { name: "Edit" })).toHaveAttribute(
      "href",
      `/people/${ids.alice}/opening/${ids.loan}/edit`,
    );
  });

  it("an evened-out entry has no Reverse", async () => {
    const { dialog } = await sheetOf(
      /^Loan.*Rent help/,
      entry({ title: "Evened out", can_reverse: false, notes: ["What each owed the other was cleared."] }),
    );
    expect(within(dialog).getByText("What each owed the other was cleared.")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Reverse" })).not.toBeInTheDocument();
  });
});
