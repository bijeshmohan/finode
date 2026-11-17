import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN, figureText } from "../../test/render";
import { group, ids } from "./fixtures";

const INR: Answers = { "/api/profile/": [200, { default_currency: "INR" }] };
const PATH = `/api/views/budget/groups/${ids.food}`;

describe("a group's budget page", () => {
  it("shows its glance and its categories", async () => {
    renderApp(`/budget/groups/${ids.food}?month=2026-11`, { ...SIGNED_IN, ...INR, [PATH]: [200, group()] });
    expect(await screen.findByRole("heading", { level: 1, name: "Food" })).toBeInTheDocument();
    expect(await screen.findByText(figureText("₹500.00"))).toBeInTheDocument();
    expect(screen.getByText("Spent 0.00 of 500.00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Dining/ })).toBeInTheDocument();
    // The way back keeps the month (the tab bar's Budgets does not).
    expect(screen.getAllByRole("link", { name: "Budgets" }).map((l) => l.getAttribute("href"))).toContain(
      "/budget?month=2026-11",
    );
  });

  it("says over budget when over, and nothing assigned when nothing is", async () => {
    renderApp(`/budget/groups/${ids.food}`, {
      ...SIGNED_IN,
      [PATH]: [200, group({ glance: { left: "-20.00", spent: "520.00", of: "520.00", percent: 100, planned: true } })],
    });
    expect(await screen.findByText("Over budget")).toBeInTheDocument();
  });

  it("its own budget below what its categories add up to is red and is not sent", async () => {
    const { fetch } = renderApp(`/budget/groups/${ids.food}`, {
      ...SIGNED_IN,
      [PATH]: [200, group()],
      [`/api/budget/groups/${ids.food}`]: [200, {}],
    });
    await userEvent.click(await screen.findByRole("button", { name: /Left to spend/ }));
    const sheet = await screen.findByRole("dialog", { name: "Food" });
    const field = within(sheet).getByLabelText("Assigned this month");
    await userEvent.clear(field);
    await userEvent.type(field, "200");
    expect(field).toHaveAttribute("aria-invalid", "true");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    expect(fetch.mock.calls.some(([r]) => r.method === "PUT")).toBe(false);
    expect(screen.getByRole("dialog", { name: "Food" })).toBeInTheDocument();
    await userEvent.clear(field);
    await userEvent.type(field, "700");
    expect(field).toHaveAttribute("aria-invalid", "false");
    await userEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(fetch.mock.calls.some(([r]) => new URL(r.url).pathname === `/api/budget/groups/${ids.food}`)).toBe(true);
    });
    const call = fetch.mock.calls.find(([r]) => r.method === "PUT");
    expect(await call?.[0].clone().json()).toEqual({ month: "2026-11-01", total: "700.00" });
  });

  it("the glance block reads what is left and spent, and opens the group's own budget", async () => {
    renderApp(`/budget/groups/${ids.food}`, { ...SIGNED_IN, ...INR, [PATH]: [200, group()] });
    const block = await screen.findByRole("button", { name: /Left to spend.*Spent 0\.00 of 500\.00/ });
    expect(block).toHaveAttribute("title", "Set the budget");
  });

  it("a group budget below zero opens as it is", async () => {
    renderApp(`/budget/groups/${ids.food}`, {
      ...SIGNED_IN,
      [PATH]: [200, group({ assigned: "-100.00", minimum: "-100.00" })],
    });
    await userEvent.click(await screen.findByRole("button", { name: /Left to spend/ }));
    const sheet = await screen.findByRole("dialog", { name: "Food" });
    expect(within(sheet).getByLabelText("Assigned this month")).toHaveValue("-100.00");
  });

  it("the old address opens the same page", async () => {
    const { router } = renderApp(`/budget/group/${ids.food}?month=2026-11`, { ...SIGNED_IN, [PATH]: [200, group()] });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/budget/groups/${ids.food}`);
    });
    expect(router.state.location.search).toBe("?month=2026-11");
  });
});
