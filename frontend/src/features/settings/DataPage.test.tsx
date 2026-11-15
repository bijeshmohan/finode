import type { QueryClient } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";

const OPTIONS = { can_import: true, can_restore: true, confirm_word: "ada@example.com", can_delete_login: true };
const READY = {
  errors: [],
  warnings: ["2 entries had no payee"],
  new_accounts: ["Assets:Bank"],
  new_categories: ["Food:Groceries"],
  accounts_reused: 1,
  transactions: 12,
  skipped_empty: 1,
  date_from: "2026-01-05",
  date_to: "2026-03-31",
  assets: "4000.00",
  liabilities: "-200.00",
};
const RESTORABLE = {
  errors: [],
  accounts: 4,
  categories: 1,
  contacts: 0,
  shared_expenses: 0,
  transactions: 20,
  recurring: 2,
  allocations: 3,
  tags: 1,
  date_from: "2026-01-01",
  date_to: "2026-02-01",
};

function open(more: Answers = {}, options = OPTIONS, seed?: (queryClient: QueryClient) => void) {
  return renderApp("/profile/data", { ...SIGNED_IN, "/api/data-options": [200, options], ...more }, seed);
}

/** What the app holds about the books besides the open screen's: a view, the tags and the payees offered. */
const HELD = [["views", "people", "all"], ["tags"], ["payee-suggestions", "", ""]];

function holdSome(queryClient: QueryClient) {
  for (const key of HELD) queryClient.setQueryData(key, []);
}

async function allRefreshed(queryClient: QueryClient) {
  await waitFor(() => {
    for (const key of HELD) expect(queryClient.getQueryState(key)?.isInvalidated, key.join("/")).toBe(true);
  });
  expect(queryClient.getQueryState(["session"])?.isInvalidated).not.toBe(true);
}

/** An answer that comes when the test says so. */
function late() {
  let finish: (answer: [number, unknown]) => void = () => undefined;
  const answer = new Promise<[number, unknown]>((resolve) => {
    finish = resolve;
  });
  return {
    answer,
    finish: (status: number, body: unknown) => {
      finish([status, body]);
    },
  };
}

async function rowOpen(name: RegExp) {
  await userEvent.click(await screen.findByRole("button", { name }));
}

function chooseFile(label: string, name: string, text: string) {
  const file = new File([text], name, { type: "text/plain" });
  fireEvent.change(screen.getByLabelText(label), { target: { files: [file] } });
}

/** The button under a row (the row's own title is a button too). */
function lastButton(name: string): HTMLElement {
  const last = screen.getAllByRole("button", { name }).at(-1);
  if (!last) throw new Error(`no ${name} button`);
  return last;
}

function calls(fetch: ReturnType<typeof renderApp>["fetch"], path: string) {
  return fetch.mock.calls.filter(([r]) => new URL(r.url).pathname === path).map(([r]) => r);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Your data", () => {
  it("offers the exports and the backup as downloads from the API", async () => {
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Your data" })).toBeInTheDocument();
    await rowOpen(/^Export/);
    expect(
      screen.getByText("Ledger format opens in hledger and similar tools; CSV opens in a spreadsheet."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Export ledger file" })).toHaveAttribute(
      "href",
      "/api/export?format=ledger",
    );
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute("href", "/api/export?format=csv");
    await rowOpen(/^Backup/);
    expect(screen.getByRole("link", { name: "Download backup" })).toHaveAttribute("href", "/api/backup");
    expect(screen.getByRole("link", { name: "Download backup" })).toHaveAttribute("download");
  });

  it("says why import and restore are not offered once there are books", async () => {
    open({}, { ...OPTIONS, can_import: false, can_restore: false });
    await rowOpen(/^Backup/);
    expect(screen.getByText("Restoring only works on an empty ledger.")).toBeInTheDocument();
    await rowOpen(/^Import/);
    expect(
      screen.getByText(
        "Importing is only available before you record transactions. Export your data first if you want to start over.",
      ),
    ).toBeInTheDocument();
  });

  it("previews an import, then imports and goes home", async () => {
    const { fetch, router } = open({ "/api/import": [200, READY] });
    await rowOpen(/^Import/);
    chooseFile("Ledger file", "books.ledger", "2026-01-05 Shop\n  a  1\n  b\n");
    await userEvent.click(screen.getByRole("button", { name: "Preview import" }));
    const preview = await screen.findByText("Ready to import");
    const box = preview.closest("div");
    if (!box) throw new Error("no preview");
    expect(within(box).getByText("12 transactions, 5 Jan 2026 to 31 Mar 2026")).toBeInTheDocument();
    expect(within(box).getByText("1 new account, 1 existing reused, 1 new category")).toBeInTheDocument();
    expect(within(box).getByText("Assets 4,000.00 · Liabilities −200.00")).toBeInTheDocument();
    expect(within(box).getByText("1 zero-amount transaction skipped")).toBeInTheDocument();
    expect(within(box).getByText("2 entries had no payee")).toBeInTheDocument();
    const [first] = calls(fetch, "/api/import");
    expect(first && new URL(first.url).searchParams.get("dry_run")).toBe("true");
    await userEvent.click(screen.getByRole("button", { name: "Import 12 transactions" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    const [, second] = calls(fetch, "/api/import");
    expect(second && new URL(second.url).searchParams.get("dry_run")).toBeNull();
    expect(await screen.findByText("Import complete")).toBeInTheDocument();
  });

  it("a preview with errors says nothing was imported and offers no import", async () => {
    open({ "/api/import": [200, { ...READY, errors: ["line 3: an entry must balance"] }] });
    await rowOpen(/^Import/);
    chooseFile("Ledger file", "books.ledger", "bad");
    await userEvent.click(screen.getByRole("button", { name: "Preview import" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nothing was imported.");
    expect(alert).toHaveTextContent("line 3: an entry must balance");
    expect(screen.queryByRole("button", { name: /^Import \d/ })).not.toBeInTheDocument();
  });

  it("previewing with no file chosen says so in the API's words", async () => {
    open();
    await rowOpen(/^Import/);
    await userEvent.click(screen.getByRole("button", { name: "Preview import" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a file first.");
  });

  it.each([
    ["import", /^Import/, "Ledger file", "Preview import", "Import 12 transactions", READY],
    ["restore", /^Backup/, "Backup file", "Preview restore", "Restore everything", RESTORABLE],
  ])("a %s that finishes after you left still refreshes everything held", async (kind, row, label, preview, go, ok) => {
    const done = late();
    const { router, queryClient } = open(
      { [`/api/${kind}`]: (url) => (url.searchParams.get("dry_run") ? [200, ok] : done.answer) },
      OPTIONS,
      holdSome,
    );
    await rowOpen(row);
    chooseFile(label, "file.txt", "x");
    await userEvent.click(screen.getByRole("button", { name: preview }));
    await userEvent.click(await screen.findByRole("button", { name: go }));
    await router.navigate("/elsewhere"); // a page that asks for nothing
    done.finish(200, ok);
    await allRefreshed(queryClient);
  });

  it("a file the server refuses shows its words", async () => {
    open({ "/api/import": [400, { detail: "The file is larger than 2 MB." }] });
    await rowOpen(/^Import/);
    chooseFile("Ledger file", "books.ledger", "x");
    await userEvent.click(screen.getByRole("button", { name: "Preview import" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The file is larger than 2 MB.");
  });

  it("previews a restore, then restores everything", async () => {
    const { router } = open({ "/api/restore": [200, RESTORABLE] });
    await rowOpen(/^Backup/);
    chooseFile("Backup file", "finode-backup.json", "{}");
    await userEvent.click(screen.getByRole("button", { name: "Preview restore" }));
    expect(await screen.findByText("Ready to restore")).toBeInTheDocument();
    expect(
      screen.getByText("4 accounts, 1 category, 20 transactions from 1 Jan 2026 to 1 Feb 2026"),
    ).toBeInTheDocument();
    expect(screen.getByText("2 recurring transactions")).toBeInTheDocument();
    expect(screen.getByText("1 tag")).toBeInTheDocument();
    expect(screen.getByText("Budget: 3 assigned amounts")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restore everything" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(await screen.findByText("Backup restored")).toBeInTheDocument();
  });

  it("a restore the server refuses lists why", async () => {
    open({ "/api/restore": [400, { detail: { ...RESTORABLE, errors: ["this is not a finode backup"] } }] });
    await rowOpen(/^Backup/);
    chooseFile("Backup file", "x.json", "{}");
    await userEvent.click(screen.getByRole("button", { name: "Preview restore" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nothing was restored.");
    expect(alert).toHaveTextContent("this is not a finode backup");
  });

  it("erases the books once the word is typed", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    let typed = "";
    const { router } = open({
      "/api/erase": () =>
        typed === "ada@example.com" ? [204, null] : [400, { detail: "Type ada@example.com to confirm." }],
    });
    await rowOpen(/^Erase my books/);
    expect(
      screen.getByText(
        "Deletes your accounts, transactions, budget and history. You keep your login, settings and assistants' access. This can't be undone: download a backup first.",
      ),
    ).toBeInTheDocument();
    const field = screen.getByLabelText(/Type ada@example.com to confirm/);
    await userEvent.type(field, "nobody");
    await userEvent.click(lastButton("Erase my books"));
    expect(ask).toHaveBeenCalledWith("Erase all your accounts, transactions and budget? This cannot be undone.");
    expect(await screen.findByRole("alert")).toHaveTextContent("Type ada@example.com to confirm.");
    typed = "ada@example.com";
    await userEvent.clear(field);
    await userEvent.type(field, typed);
    await userEvent.click(lastButton("Erase my books"));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(await screen.findByText("Your books were erased")).toBeInTheDocument();
  });

  it("an erase that finishes after you left still refreshes everything held", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const done = late();
    const { router, queryClient } = open({ "/api/erase": () => done.answer }, OPTIONS, holdSome);
    await rowOpen(/^Erase my books/);
    await userEvent.type(screen.getByLabelText(/Type ada@example.com to confirm/), "ada@example.com");
    await userEvent.click(lastButton("Erase my books"));
    await router.navigate("/elsewhere"); // a page that asks for nothing
    done.finish(204, null);
    await allRefreshed(queryClient);
  });

  it("a delete that erased the books but kept the login refreshes what is held", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { queryClient } = open(
      { "/api/delete-account": [503, { detail: "Your data was erased, but removing your login failed." }] },
      OPTIONS,
      holdSome,
    );
    await rowOpen(/^Delete my account/);
    await userEvent.type(screen.getByLabelText(/Type ada@example.com to confirm/), "ada@example.com");
    await userEvent.click(lastButton("Delete my account"));
    expect(await screen.findByRole("alert")).toHaveTextContent("removing your login failed");
    await allRefreshed(queryClient);
  });

  it("deletes the account and signs out", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { router, fetch } = open({ "/api/delete-account": [204, null] });
    await rowOpen(/^Delete my account/);
    await userEvent.type(screen.getByLabelText(/Type ada@example.com to confirm/), "ada@example.com");
    await userEvent.click(lastButton("Delete my account"));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/sign-in");
    });
    expect(calls(fetch, "/api/delete-account")).toHaveLength(1);
    expect(await screen.findByText("Your account was deleted. Goodbye!")).toBeInTheDocument();
  });

  it("without a way to remove logins Delete only explains", async () => {
    open({}, { ...OPTIONS, can_delete_login: false });
    await rowOpen(/^Delete my account/);
    expect(
      screen.getByText(
        "Deleting your login isn't set up here. Erase your books above and ask the person who runs finode to remove your login.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Delete my account" })).toHaveLength(1);
  });
});
