import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, calledPaths, renderInApp, SIGNED_IN } from "../../test/render";
import { row } from "../transactions/fixtures";
import { EntryScreen } from "./EntryScreen";
import { ids, view } from "./fixtures";
import { cleanTag } from "./NoteAndTags";

const BASE: Answers = {
  ...SIGNED_IN,
  "/api/entries": [201, { transaction_id: "t1", recorded: "transaction" }],
  "/api/transactions/payee-suggestions": (url) =>
    (url.searchParams.get("payee") ?? "").startsWith("@")
      ? [200, { names: [], people: [{ id: ids.ada, name: "Ada" }] }]
      : [
          200,
          {
            names: ["Swiggy", "Swiggy Instamart"].filter((n) =>
              n.toLowerCase().startsWith((url.searchParams.get("payee") ?? "").toLowerCase()),
            ),
            people: [],
          },
        ],
  "/api/tags/": [200, [{ tag: "goa-trip", uses: 2, last_used: "2026-11-01" }]],
  "/api/views/related-entries": (url) => [
    200,
    [row({ id: "r1", title: "Amazon", amount: "4998.00", date: "2026-11-02" })].filter((r) =>
      r.title.toLowerCase().includes((url.searchParams.get("q") ?? "").toLowerCase()),
    ),
  ],
};

async function open(answers: Answers = {}) {
  const rendered = renderInApp(<EntryScreen form={view()} />, { ...BASE, ...answers });
  await screen.findByLabelText("Amount");
  return rendered;
}

async function saveExpense() {
  await userEvent.type(screen.getByLabelText("Amount"), "30");
  await userEvent.click(screen.getByRole("button", { name: /^Paid from/ }));
  await userEvent.click(await screen.findByRole("button", { name: /Bank/ }));
  await userEvent.click(screen.getByRole("button", { name: /^Spent on/ }));
  await userEvent.click(await screen.findByRole("button", { name: /Food/ }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
}

async function sent(fetch: Awaited<ReturnType<typeof open>>["fetch"]) {
  await waitFor(() => {
    expect(calledPaths(fetch)).toContain("/api/entries");
  });
  const call = fetch.mock.calls.find(([r]) => new URL(r.url).pathname === "/api/entries");
  if (!call) throw new Error("not sent");
  return (await call[0].clone().json()) as Record<string, unknown>;
}

describe("the payee", () => {
  it("a chip fills the payee only, and the chips narrow as you type", async () => {
    await open();
    await userEvent.type(screen.getByPlaceholderText("Payee or Merchant?"), "swiggy i");
    const chips = await screen.findByRole("group", { name: "People you pay" });
    expect(chips).toHaveTextContent("Swiggy Instamart");
    expect(chips).not.toHaveTextContent(/^Swiggy$/);
    await userEvent.click(screen.getByRole("button", { name: "Swiggy Instamart" }));
    expect(screen.getByPlaceholderText("Payee or Merchant?")).toHaveValue("Swiggy Instamart");
    expect(screen.getByRole("button", { name: /^Paid from/ })).toHaveTextContent("Account…");
  });

  it("after an @, a person is named on the entry and sent with it", async () => {
    const { fetch } = await open();
    await userEvent.type(screen.getByPlaceholderText("Payee or Merchant?"), "@a");
    await userEvent.click(await screen.findByRole("button", { name: "Ada" }));
    expect(screen.getByText("Nothing is owed.", { exact: false })).toBeInTheDocument();
    await saveExpense();
    expect(await sent(fetch)).toMatchObject({ payee: "Ada", payee_contact: ids.ada });
  });

  it("a transfer cannot name a person: switching to one takes them off", async () => {
    await open();
    await userEvent.type(screen.getByPlaceholderText("Payee or Merchant?"), "@a");
    await userEvent.click(await screen.findByRole("button", { name: "Ada" }));
    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));
    expect(screen.queryByText("Nothing is owed.", { exact: false })).not.toBeInTheDocument();
  });
});

describe("the date", () => {
  it("is a chip that names the day", async () => {
    await open();
    expect(screen.getByLabelText("Date").closest("label")).toHaveTextContent("Today, 13 Nov");
  });
});

describe("a related entry", () => {
  it("is chosen in a sheet, sent with the entry, and the chip removes it", async () => {
    const { fetch } = await open();
    await userEvent.click(screen.getByRole("button", { name: "Related" }));
    await userEvent.type(await screen.findByLabelText("Search transactions"), "ama");
    await userEvent.click(await screen.findByRole("button", { name: /Amazon/ }));
    expect(screen.getByText("Related to")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove the link" }));
    expect(screen.getByRole("button", { name: "Related" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Related" }));
    await userEvent.click(await screen.findByRole("button", { name: /Amazon/ }));
    await saveExpense();
    expect(await sent(fetch)).toMatchObject({ related_id: "r1" });
  });
});

describe("the note and its tags", () => {
  it("tags chosen and made in the sheet are sent; a # in the note stays text", async () => {
    const { fetch } = await open();
    await userEvent.type(screen.getByLabelText("Note"), "lunch #work");
    await userEvent.click(screen.getByRole("button", { name: "Tags" }));
    await userEvent.click(await screen.findByRole("button", { name: /#goa-trip/ }));
    await userEvent.type(screen.getByLabelText("Search or create a tag"), "Team Lunch");
    await userEvent.click(screen.getByRole("button", { name: "＋ Create “#team-lunch”" }));
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByRole("button", { name: "Change the tags" })).toHaveTextContent("#goa-trip#team-lunch");
    await saveExpense();
    expect(await sent(fetch)).toMatchObject({ comment: "lunch #work", tags: ["goa-trip", "team-lunch"] });
  });

  it("cleans a typed tag as the server keeps it", () => {
    expect(cleanTag(" #Goa Trip ")).toBe("goa-trip");
  });
});
