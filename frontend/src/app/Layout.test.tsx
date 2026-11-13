import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../test/render";

describe("the layout", () => {
  it("has a tab bar with the four pages and the plus button", async () => {
    renderApp("/");
    const tabs = await screen.findByRole("navigation", { name: "Tab bar" });
    for (const name of ["Home", "Budgets", "Accounts", "Categories", "New transaction"]) {
      expect(within(tabs).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(within(tabs).getByRole("link", { name: "New transaction" })).toHaveAttribute("href", "/transactions/new");
  });

  it("has a sidebar with every page for wide screens", async () => {
    renderApp("/");
    const side = await screen.findByRole("navigation", { name: "Sidebar" });
    for (const name of ["Home", "Budgets", "Accounts", "Categories", "Transactions", "People", "Settings"]) {
      expect(within(side).getByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("marks the current page", async () => {
    renderApp("/accounts");
    const tabs = await screen.findByRole("navigation", { name: "Tab bar" });
    expect(within(tabs).getByRole("link", { name: "Accounts" })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
  });
});

describe("the brand", () => {
  it("says finode and leads home", async () => {
    renderApp("/accounts");
    const brands = await screen.findAllByRole("link", { name: "finode" });
    expect(brands[0]).toHaveAttribute("href", "/");
  });
});
