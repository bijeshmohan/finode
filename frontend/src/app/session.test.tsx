import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp, SIGNED_IN } from "../test/render";

describe("the session", () => {
  it("signed out goes to sign-in", async () => {
    const { router } = renderApp("/accounts", {
      "/api/auth/session": [401, { detail: "missing authentication token" }],
    });
    expect(await screen.findByText("Sign in to your ledger.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(router.state.location.search).toBe("?next=%2Faccounts");
  });

  it("a lost connection says so and offers to try again, never sign-in", async () => {
    renderApp("/", { "/api/auth/session": new TypeError("Failed to fetch") });
    expect(await screen.findByText("finode can't be reached. Check your connection.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText("Sign in to your ledger.")).not.toBeInTheDocument();
  });

  it("a failed refresh keeps the app on screen once it has a session", async () => {
    const answers = { ...SIGNED_IN };
    const { queryClient } = renderApp("/", answers);
    expect(await screen.findByRole("heading", { name: "Home" })).toBeInTheDocument();
    answers["/api/auth/session"] = new TypeError("Failed to fetch");
    await act(() => queryClient.refetchQueries({ queryKey: ["session"] }));
    await waitFor(() => {
      expect(queryClient.getQueryState(["session"])?.status).toBe("error");
    });
    expect(screen.getByRole("heading", { name: "Home" })).toBeInTheDocument();
    expect(screen.queryByText("finode can't be reached. Check your connection.")).not.toBeInTheDocument();
  });

  it("today is the server's day", async () => {
    renderApp("/people", SIGNED_IN);
    expect(await screen.findByRole("heading", { name: "People" })).toBeInTheDocument();
    expect(screen.getByTestId("today")).toHaveTextContent("2026-11-13");
  });
});
