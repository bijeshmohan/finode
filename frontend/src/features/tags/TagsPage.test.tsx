import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import type { Tag } from "./queries";

const TAGS: Tag[] = [
  { tag: "goa-trip", uses: 3, last_used: "2026-10-04" },
  { tag: "home", uses: 1, last_used: "2026-11-02" },
];

function open(tags: Tag[] = TAGS, more: Answers = {}) {
  return renderApp("/tags", { ...SIGNED_IN, "/api/tags/": [200, tags], ...more });
}

function sent(fetch: ReturnType<typeof renderApp>["fetch"], method: string) {
  return fetch.mock.calls.find(([r]) => r.method === method)?.[0];
}

async function sheetOf(name: string) {
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(`#${name}`) }));
  return screen.findByRole("dialog", { name: `#${name}` });
}

/** The Rename button under the field (the first one opens the field). */
async function submitRename(sheet: HTMLElement) {
  const last = within(sheet).getAllByRole("button", { name: "Rename" }).at(-1);
  if (!last) throw new Error("no Rename button");
  await userEvent.click(last);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the Tags page", () => {
  it("lists the tags with their counts in one tile", async () => {
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Tags" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Settings" }).map((l) => l.getAttribute("href"))).toContain("/settings");
    const goa = await screen.findByRole("button", { name: /#goa-trip/ });
    expect(goa).toHaveTextContent("#goa-trip3");
    expect(screen.getByRole("button", { name: /#home/ })).toHaveTextContent("1");
  });

  it("with no tags says how to add one", async () => {
    open([]);
    expect(
      await screen.findByText("No tags yet. Add one with the # button when you record or edit an entry."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Record a transaction" })).toHaveAttribute("href", "/transactions/new");
  });

  it("a tag's sheet says how often it was used and shows its entries", async () => {
    open();
    const sheet = await sheetOf("goa-trip");
    expect(within(sheet).getByText("3 entries · last used Sun, 4 Oct")).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: /View entries/ })).toHaveAttribute(
      "href",
      "/transactions?month=2026-10&tag=goa-trip",
    );
  });

  it("one entry reads in the singular, and with no other tag there is nothing to merge into", async () => {
    open([{ tag: "home", uses: 1, last_used: "2026-11-02" }]);
    const sheet = await sheetOf("home");
    expect(within(sheet).getByText("1 entry · last used Mon, 2 Nov")).toBeInTheDocument();
    expect(within(sheet).queryByRole("button", { name: "Merge into…" })).not.toBeInTheDocument();
  });

  it("renames", async () => {
    const { fetch } = open(TAGS, { "/api/tags/goa-trip": [200, { tag: "goa", uses: 3, last_used: "2026-10-04" }] });
    const sheet = await sheetOf("goa-trip");
    await userEvent.click(within(sheet).getByRole("button", { name: "Rename" }));
    const field = within(sheet).getByRole("textbox", { name: "New name" });
    expect(field).toHaveValue("goa-trip");
    expect(within(sheet).getByText("If the new name is another of your tags, the two become one.")).toBeInTheDocument();
    await userEvent.clear(field);
    await userEvent.type(field, "goa");
    await submitRename(sheet);
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "#goa-trip" })).not.toBeInTheDocument();
    });
    const patch = sent(fetch, "PATCH");
    expect(patch && new URL(patch.url).pathname).toBe("/api/tags/goa-trip");
    expect(await patch?.clone().json()).toEqual({ name: "goa" });
    expect(await screen.findByText("Tag renamed")).toBeInTheDocument();
  });

  it("merges into another tag", async () => {
    const { fetch } = open(TAGS, { "/api/tags/goa-trip": [200, { tag: "home", uses: 4, last_used: "2026-11-02" }] });
    const sheet = await sheetOf("goa-trip");
    await userEvent.click(within(sheet).getByRole("button", { name: "Merge into…" }));
    await userEvent.selectOptions(within(sheet).getByRole("combobox", { name: "Merge into" }), "home");
    await userEvent.click(within(sheet).getByRole("button", { name: "Merge" }));
    await waitFor(() => {
      expect(sent(fetch, "PATCH")).toBeDefined();
    });
    expect(await sent(fetch, "PATCH")?.clone().json()).toEqual({ name: "home" });
    expect(await screen.findByText("Tags merged")).toBeInTheDocument();
  });

  it("deletes after asking", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { fetch } = open(TAGS, { "/api/tags/goa-trip": [204, null] });
    const sheet = await sheetOf("goa-trip");
    await userEvent.click(within(sheet).getByRole("button", { name: "Delete tag" }));
    expect(ask).toHaveBeenCalledWith("Delete the tag goa-trip? It comes off 3 entries; they are not deleted.");
    await waitFor(() => {
      expect(sent(fetch, "DELETE")).toBeDefined();
    });
    expect(await screen.findByText("Tag deleted")).toBeInTheDocument();
  });

  it("a refusal stays in the sheet", async () => {
    open(TAGS, {
      "/api/tags/goa-trip": [400, { detail: "'goa trip' cannot be a tag: use 1 to 30 letters, digits, - or _!" }],
    });
    const sheet = await sheetOf("goa-trip");
    await userEvent.click(within(sheet).getByRole("button", { name: "Rename" }));
    const field = within(sheet).getByRole("textbox", { name: "New name" });
    await userEvent.clear(field);
    await userEvent.type(field, "goa trip");
    await submitRename(sheet);
    expect(await within(sheet).findByRole("alert")).toHaveTextContent(/cannot be a tag/);
    expect(screen.getByRole("dialog", { name: "#goa-trip" })).toBeInTheDocument();
  });
});
