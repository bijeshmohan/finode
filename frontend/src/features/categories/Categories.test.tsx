import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { calledPaths, renderApp, SIGNED_IN } from "../../test/render";
import { categories, category, categoryForm, ids } from "./fixtures";

const INR = { "/api/profile/": [200, { default_currency: "INR" }] as [number, unknown] };

async function sent(fetch: ReturnType<typeof renderApp>["fetch"], path: string, method: string) {
  await waitFor(() => {
    expect(fetch.mock.calls.some(([r]) => new URL(r.url).pathname === path && r.method === method)).toBe(true);
  });
  const call = fetch.mock.calls.find(([r]) => new URL(r.url).pathname === path && r.method === method);
  if (!call) throw new Error("nothing sent");
  return (await call[0].clone().json()) as Record<string, unknown>;
}

describe("the Categories page", () => {
  it("ranks the month's categories with what is inside and their share", async () => {
    renderApp("/categories", { ...SIGNED_IN, ...INR, "/api/views/categories": [200, categories()] });
    expect(await screen.findByText("₹1,000.00")).toBeInTheDocument();
    expect(screen.getByText("Spent so far")).toBeInTheDocument();
    expect(screen.getByText("3 categories")).toBeInTheDocument();
    const food = screen.getByRole("link", { name: /Food/ });
    expect(food).toHaveAttribute("href", `/categories/${ids.food}?month=2026-11`);
    expect(food).toHaveTextContent("Groceries · Dining · 40%");
    expect(screen.getByRole("link", { name: /Rent/ })).toHaveTextContent("60% of spending");
    expect(screen.getByRole("link", { name: /Travel/ })).toHaveTextContent("Nothing yet");
    expect(screen.getByRole("link", { name: "Add category" })).toHaveAttribute("href", "/categories/new?root=expense");
  });

  it("the tab and the month live in the address", async () => {
    const asked: string[] = [];
    const { router } = renderApp("/categories?month=2026-10&tab=income", {
      ...SIGNED_IN,
      "/api/views/categories": (url) => {
        asked.push(url.search);
        return [200, categories({ month: "2026-10", is_current: false, tab: "income" })];
      },
    });
    expect(await screen.findByText("Earned in October")).toBeInTheDocument();
    expect(asked[0]).toBe("?month=2026-10&tab=income");
    await userEvent.click(screen.getByRole("radio", { name: "Spending" }));
    await waitFor(() => {
      expect(router.state.location.search).toBe("?month=2026-10&tab=expense");
    });
  });
});

describe("a category's page", () => {
  const path = `/api/views/categories/${ids.food}`;

  it("a group shows its month, its subcategories and everything else", async () => {
    renderApp(`/categories/${ids.food}`, { ...SIGNED_IN, ...INR, [path]: [200, category()] });
    expect(await screen.findByRole("heading", { level: 1, name: "Food" })).toBeInTheDocument();
    expect(screen.getByText("Spending")).toBeInTheDocument();
    expect(await screen.findByText("₹350.00")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Groceries/ })).toHaveAttribute(
      "href",
      `/categories/${ids.groceries}?month=2026-11`,
    );
    expect(screen.getByText("Everything else")).toBeInTheDocument();
    expect(screen.getByText("posted to Food itself")).toBeInTheDocument();
  });

  it("a category with nothing in the month says so", async () => {
    renderApp(`/categories/${ids.food}`, {
      ...SIGNED_IN,
      [path]: [200, category({ subs: [], own_here: "0.00", total: "0.00", month: "2026-10", is_current: false })],
    });
    expect(await screen.findByText("Nothing in October.")).toBeInTheDocument();
  });

  it("delete asks first and goes back to the Categories page", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { router } = renderApp(`/categories/${ids.food}`, {
      ...SIGNED_IN,
      [path]: [200, category()],
      [`/api/categories/${ids.food}/delete`]: [200, { deleted: true }],
      "/api/views/categories": [200, categories()],
    });
    await userEvent.click(await screen.findByLabelText("More actions"));
    await userEvent.click(screen.getByRole("button", { name: "Delete category" }));
    expect(confirm).toHaveBeenCalledWith(
      "Delete Food and the subcategories in it? If there are entries, they stay in your history and reports, but these categories leave your lists and pickers.",
    );
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/categories");
    });
  });

  it("deleting an unused category does not ask for its page again", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let deleted = false;
    let asked = 0;
    const { router } = renderApp(`/categories/${ids.food}`, {
      ...SIGNED_IN,
      [path]: () => {
        asked += 1;
        return deleted ? [404, { detail: "category not found" }] : [200, category({ subs: [] })];
      },
      [`/api/categories/${ids.food}/delete`]: () => {
        deleted = true;
        return [200, { outcome: "deleted" }];
      },
      "/api/views/categories": [200, categories()],
    });
    await userEvent.click(await screen.findByLabelText("More actions"));
    await userEvent.click(screen.getByRole("button", { name: "Delete category" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/categories");
    });
    expect(asked).toBe(1);
  });

  it("the + starts an entry for the category as the server says", async () => {
    renderApp(`/categories/${ids.food}`, {
      ...SIGNED_IN,
      [path]: [200, category({ new_transaction_url: "/transactions/new?category=x&back=/categories/x" })],
    });
    await screen.findByRole("heading", { level: 1, name: "Food" });
    const tabs = screen.getByRole("navigation", { name: "Tab bar" });
    expect(within(tabs).getByRole("link", { name: "New transaction" })).toHaveAttribute(
      "href",
      "/transactions/new?category=x&back=/categories/x",
    );
  });

  it("a deleted category can be restored", async () => {
    const { fetch } = renderApp(`/categories/${ids.food}`, {
      ...SIGNED_IN,
      [path]: [200, category({ closed_on: "2026-11-02", can_delete: false })],
      [`/api/categories/${ids.food}/reopen`]: [200, {}],
    });
    expect(await screen.findByText(/Closed on 02 Nov 2026/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("More actions"));
    await userEvent.click(screen.getByRole("button", { name: "Restore category" }));
    await waitFor(() => {
      expect(calledPaths(fetch)).toContain(`/api/categories/${ids.food}/reopen`);
    });
    expect(await screen.findByText("Category restored")).toBeInTheDocument();
  });
});

describe("the category form", () => {
  it("adds a category under a group chosen in the picker", async () => {
    const { fetch, router } = renderApp("/categories/new", {
      ...SIGNED_IN,
      "/api/views/category-form": [200, categoryForm()],
      "/api/categories/": [201, { id: ids.groceries }],
    });
    await userEvent.type(await screen.findByLabelText("Name"), "Groceries");
    await userEvent.click(screen.getByRole("button", { name: /^Under/ }));
    await userEvent.click(
      within(await screen.findByRole("dialog", { name: "Under" })).getByRole("button", { name: /Food/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Add category" }));
    expect(await sent(fetch, "/api/categories/", "POST")).toEqual({
      name: "Groceries",
      kind: "spending",
      parent_id: ids.food,
      details: null,
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/categories/${ids.groceries}`);
    });
  });

  it("an edit sends only what changed, and Under can be none", async () => {
    const { fetch } = renderApp(`/categories/${ids.groceries}/edit`, {
      ...SIGNED_IN,
      "/api/views/category-form": [200, categoryForm({ editing: true, name: "Groceries", parent_id: ids.food })],
      [`/api/categories/${ids.groceries}`]: [200, { id: ids.groceries }],
    });
    await userEvent.click(await screen.findByRole("button", { name: /^Under/ }));
    await userEvent.click(
      within(await screen.findByRole("dialog", { name: "Under" })).getByRole("button", { name: "None (top level)" }),
    );
    expect(screen.getByRole("button", { name: /^Under/ })).toHaveTextContent("None (top level)");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await sent(fetch, `/api/categories/${ids.groceries}`, "PATCH")).toEqual({ parent_id: null });
  });
});
