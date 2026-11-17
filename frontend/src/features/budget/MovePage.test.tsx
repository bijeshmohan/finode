import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";
import { budget, ids } from "./fixtures";

const MOVE: Answers = {
  "/api/views/budget-move": [
    200,
    {
      month: "2026-11",
      source: ids.rent,
      lines: [
        { category_id: ids.rent, path: "Rent", available: "500.00" },
        { category_id: ids.dining, path: "Food › Dining", available: "120.00" },
      ],
    },
  ],
};

describe("Move money", () => {
  it("starts from the source and moves to the category chosen", async () => {
    const { fetch, router } = renderApp(`/budget/move?month=2026-11&source=${ids.rent}`, {
      ...SIGNED_IN,
      ...MOVE,
      "/api/budget/move": [200, {}],
      "/api/views/budget": [200, budget()],
    });
    expect(
      await screen.findByText(/November 2026 · from one category's available money to another/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^From/ })).toHaveTextContent("Rent");
    await userEvent.type(screen.getByLabelText("Amount"), "120");
    await userEvent.click(screen.getByRole("button", { name: /^To(?! do)/ }));
    const sheet = await screen.findByRole("dialog", { name: "To" });
    expect(within(sheet).getByRole("button", { name: /Food › Dining/ })).toHaveTextContent("120.00 left");
    await userEvent.click(within(sheet).getByRole("button", { name: /Food › Dining/ }));
    await userEvent.click(screen.getByRole("button", { name: "Move money" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/budget");
    });
    const call = fetch.mock.calls.find(([r]) => new URL(r.url).pathname === "/api/budget/move");
    expect(await call?.[0].clone().json()).toEqual({
      month: "2026-11-01",
      from_category: ids.rent,
      to_category: ids.dining,
      amount: "120.00",
    });
    expect(router.state.location.search).toBe("?month=2026-11");
  });

  it("needs both categories", async () => {
    const { fetch } = renderApp("/budget/move", { ...SIGNED_IN, ...MOVE });
    await userEvent.type(await screen.findByLabelText("Amount"), "10");
    await userEvent.click(screen.getByRole("button", { name: "Move money" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose the category to move from and the one to move to.",
    );
    expect(fetch.mock.calls.some(([r]) => r.method === "POST")).toBe(false);
  });

  it("a refusal shows the server's words", async () => {
    renderApp(`/budget/move?source=${ids.rent}`, {
      ...SIGNED_IN,
      ...MOVE,
      "/api/budget/move": [400, { detail: "Rent has only 500.00 available to move!" }],
    });
    await userEvent.type(await screen.findByLabelText("Amount"), "900");
    await userEvent.click(screen.getByRole("button", { name: /^To(?! do)/ }));
    await userEvent.click(
      within(await screen.findByRole("dialog", { name: "To" })).getByRole("button", { name: /Dining/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Move money" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Rent has only 500.00 available to move!");
  });
});
