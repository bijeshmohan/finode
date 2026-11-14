import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderApp, SIGNED_IN } from "../../test/render";
import { ids, view } from "./fixtures";

describe("the Add and Edit addresses", () => {
  it("passes how the entry starts to the form's view", async () => {
    const asked: string[] = [];
    renderApp(`/transactions/new?repeat=r1&back=%2Fbudget`, {
      ...SIGNED_IN,
      "/api/views/entry-form": (url) => {
        asked.push(url.search);
        return [200, view({ payee: "Swiggy" })];
      },
    });
    expect(await screen.findByPlaceholderText("Payee or Merchant?")).toHaveValue("Swiggy");
    expect(asked[0]).toBe("?repeat=r1");
    expect(screen.getByRole("link", { name: "Back" })).toHaveAttribute("href", "/budget");
  });

  it("edits the entry in the address", async () => {
    const asked: string[] = [];
    renderApp(`/transactions/t9/edit`, {
      ...SIGNED_IN,
      "/api/views/entry-form": (url) => {
        asked.push(url.search);
        return [200, view({ editing: true })];
      },
    });
    expect(await screen.findByRole("button", { name: "Save changes" })).toBeInTheDocument();
    expect(asked[0]).toBe("?transaction_id=t9");
  });

  it("an entry a person's page looks after opens that page", async () => {
    const { router } = renderApp(`/transactions/t9/edit`, {
      ...SIGNED_IN,
      "/api/views/entry-form": [200, view({ editing: true, person_page: ids.ada })],
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/people/${ids.ada}`);
    });
  });

  it("an entry that cannot be found says so", async () => {
    renderApp(`/transactions/t9/edit`, {
      ...SIGNED_IN,
      "/api/views/entry-form": [404, { detail: "transaction not found" }],
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("transaction not found");
  });

  it("deleting from the Edit screen goes back, not to an entry that cannot be found", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let deleted = false;
    const { router } = renderApp(`/transactions/t9/edit`, {
      ...SIGNED_IN,
      "/api/views/entry-form": () =>
        deleted ? [404, { detail: "transaction not found" }] : [200, view({ editing: true })],
      "/api/transactions/t9": () => {
        deleted = true;
        return [200, {}];
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Delete transaction" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/transactions");
    });
  });
});
