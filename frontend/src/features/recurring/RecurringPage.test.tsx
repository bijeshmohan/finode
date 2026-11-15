import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import { list, rule, RULE } from "./fixtures";
import type { RecurringView } from "./queries";

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };

function open(view: RecurringView) {
  return renderApp("/recurring", { ...SIGNED_IN, ...INR, "/api/views/recurring": [200, view] });
}

describe("the Recurring list", () => {
  it("reads each rule's schedule and when it records next", async () => {
    open(list());
    expect(await screen.findByRole("heading", { level: 1, name: "Recurring" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Settings" }).map((l) => l.getAttribute("href"))).toContain("/settings");
    const row = await screen.findByRole("link", { name: /Landlord/ });
    expect(row).toHaveAttribute("href", `/recurring/${RULE}/edit`);
    expect(row).toHaveTextContent("Every month · next 1 Dec");
    expect(row).toHaveTextContent("1,500.00");
    expect(screen.getByRole("link", { name: "New recurring" })).toHaveAttribute("href", "/recurring/new");
  });

  it("a rule that could not be recorded says why", async () => {
    open(list({ live: [rule({ status: "error", last_error: "Bank can no longer be posted to" })] }));
    expect(await screen.findByRole("link", { name: /Landlord/ })).toHaveTextContent(
      "Couldn't record: Bank can no longer be posted to",
    );
  });

  it("paused and ended rules sit under Paused", async () => {
    open(
      list({
        live: [],
        stopped: [
          rule({ id: "p1", title: "Gym", status: "paused" }),
          rule({ id: "e1", title: "Course", status: "ended" }),
        ],
      }),
    );
    const paused = (await screen.findByRole("heading", { name: "Paused" })).closest("section");
    if (!paused) throw new Error("no section");
    expect(within(paused).getByRole("link", { name: /Gym/ })).toHaveTextContent("Every month · paused");
    expect(within(paused).getByRole("link", { name: /Course/ })).toHaveTextContent("Every month · ended");
  });

  it("with nothing on repeat says what it is for", async () => {
    open(list({ live: [] }));
    expect(
      await screen.findByText("Nothing on repeat yet. Rent, salary, subscriptions: set once, recorded on schedule."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New recurring" })).toBeInTheDocument();
  });
});
