import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import { ids, people } from "./fixtures";
import type { PeopleView } from "./queries";

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };

function open(view: PeopleView | ((url: URL) => [number, unknown]), path = "/people") {
  return renderApp(path, {
    ...SIGNED_IN,
    ...INR,
    "/api/views/people": typeof view === "function" ? view : [200, view],
  });
}

describe("the People list", () => {
  it("says what is owed in all and lists each person", async () => {
    open(people());
    expect(await screen.findByRole("heading", { level: 1, name: "People" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Settings" }).map((l) => l.getAttribute("href"))).toContain("/settings");
    expect(await screen.findByText("Owed to you")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("people-figure")).toHaveTextContent("₹300.00");
    });
    expect(screen.getByText("500.00 owed to you · 200.00 you owe")).toBeInTheDocument();
    const alice = screen.getByRole("link", { name: /Alice/ });
    expect(alice).toHaveAttribute("href", `/people/${ids.alice}`);
    expect(alice).toHaveTextContent("Last 2 Nov");
    expect(within(alice).getByText("500.00")).toHaveClass(/income/);
    const bob = screen.getByRole("link", { name: /Bob/ });
    expect(within(bob).getByText("200.00")).toHaveClass(/out/);
    expect(screen.getByRole("link", { name: "Add person" })).toHaveAttribute("href", "/people/new");
  });

  it("reads you owe when you owe more, in total when only one way, settled when nothing is owed", async () => {
    open(people({ owed_total: "0.00", owe_total: "200.00", difference: "200.00", label: "You owe", rows: [] }));
    expect(await screen.findByTestId("people-head")).toHaveTextContent(/^You owe/);
    expect(screen.getByText("in total")).toBeInTheDocument();
  });

  it("everything settled has no figure", async () => {
    open(
      people({
        owed_total: "0.00",
        owe_total: "0.00",
        difference: "0.00",
        label: "Everything is settled",
        rows: [{ id: ids.alice, name: "Alice", sub: "Settled up", net: "0.00" }],
      }),
    );
    expect(await screen.findByText("Everything is settled")).toBeInTheDocument();
    expect(screen.queryByTestId("people-figure")).not.toBeInTheDocument();
    expect(within(screen.getByRole("link", { name: /Alice/ })).getByText("–")).toBeInTheDocument();
  });

  it("switches between who owes whom, and offers Archived once someone is", async () => {
    const asked: string[] = [];
    open((url) => {
      asked.push(url.searchParams.get("show") ?? "");
      return [200, people({ has_archived: true, show: (url.searchParams.get("show") ?? "all") as PeopleView["show"] })];
    });
    const chips = await screen.findByRole("radiogroup", { name: "Show" });
    expect(
      within(chips)
        .getAllByRole("radio")
        .map((r) => r.textContent),
    ).toEqual(["All", "Owe you", "You owe", "Archived"]);
    await userEvent.click(within(chips).getByRole("radio", { name: "Owe you" }));
    expect(asked).toContain("owed");
  });

  it("with nobody at all offers to add someone", async () => {
    open(people({ everyone: false, rows: [], owed_total: "0.00", owe_total: "0.00", difference: "0.00" }));
    expect(await screen.findByText("Keep track of money you lend, borrow and share with people.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a person" })).toHaveAttribute("href", "/people/new");
    expect(screen.queryByRole("radiogroup", { name: "Show" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add person" })).not.toBeInTheDocument();
  });

  it("a switch with nobody in it says so", async () => {
    open(people({ show: "owe", rows: [] }), "/people?show=owe");
    expect(await screen.findByText("Nobody here.")).toBeInTheDocument();
  });

  it("the archived have no add row", async () => {
    open(
      people({
        show: "archived",
        has_archived: true,
        rows: [{ id: ids.bob, name: "Bob", sub: "Archived", net: "0.00" }],
      }),
      "/people?show=archived",
    );
    expect(await screen.findByRole("link", { name: /Bob/ })).toHaveTextContent("Archived");
    expect(screen.queryByRole("link", { name: "Add person" })).not.toBeInTheDocument();
  });
});
