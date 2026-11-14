import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client";

import { type Answers, calledPaths, renderApp, SIGNED_IN } from "../../test/render";
import { UNREACHABLE } from "./messages";

const OPTIONS_OFF: Answers = {
  "/api/auth/options": [200, { signup_enabled: false, reset_enabled: false, test_notice: false }],
};

async function signIn(password = "secret") {
  await userEvent.type(await screen.findByLabelText("Email"), "a@b.co");
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("signing in", () => {
  it("shows the form with today's words", async () => {
    renderApp("/sign-in", OPTIONS_OFF);
    expect(await screen.findByText("Sign in to your ledger.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
  });

  it("a wrong password shows the server's message", async () => {
    renderApp("/sign-in", {
      ...OPTIONS_OFF,
      "/api/auth/sign-in": [401, { detail: { message: "Invalid email or password.", code: null } }],
    });
    await signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
  });

  it("too many attempts shows the wait, and the button works again", async () => {
    const wait = "Too many sign-in attempts. Try again in 15 minutes.";
    renderApp("/sign-in", { ...OPTIONS_OFF, "/api/auth/sign-in": [429, { detail: { message: wait, code: null } }] });
    await signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent(wait);
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("a lost connection says so", async () => {
    renderApp("/sign-in", { ...OPTIONS_OFF, "/api/auth/sign-in": new TypeError("Failed to fetch") });
    await signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent(UNREACHABLE);
  });

  it("the button is disabled while signing in, so it cannot send twice", async () => {
    const { fetch } = renderApp("/sign-in", { ...OPTIONS_OFF, "/api/auth/sign-in": "never" });
    await signIn();
    const button = screen.getByRole("button", { name: "Sign in" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(calledPaths(fetch).filter((p) => p === "/api/auth/sign-in")).toHaveLength(1);
  });

  it("success goes where you were going", async () => {
    renderApp("/sign-in?next=%2Faccounts", { ...SIGNED_IN, ...OPTIONS_OFF, "/api/auth/sign-in": [204, null] });
    await signIn();
    expect(await screen.findByRole("heading", { name: "Accounts" })).toBeInTheDocument();
  });

  it("success never leaves the app, whatever next says", async () => {
    const { router } = renderApp("/sign-in?next=%2F%2Fevil.example", {
      ...SIGNED_IN,
      ...OPTIONS_OFF,
      "/api/auth/sign-in": [204, null],
    });
    await signIn();
    expect(await screen.findByRole("heading", { name: "Home" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
  });

  it("the links follow what the server offers", async () => {
    renderApp("/sign-in", OPTIONS_OFF);
    await screen.findByText("Sign in to your ledger.");
    expect(screen.queryByRole("link", { name: "Forgot your password?" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create an account" })).not.toBeInTheDocument();
  });

  it("offers forgotten password and sign-up when they are on", async () => {
    renderApp("/sign-in", {
      "/api/auth/options": [200, { signup_enabled: true, reset_enabled: true, test_notice: false }],
    });
    expect(await screen.findByRole("link", { name: "Forgot your password?" })).toHaveAttribute("href", "/forgot");
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/sign-up");
  });

  it("an account just made says so", async () => {
    renderApp("/sign-in?created=1", OPTIONS_OFF);
    expect(await screen.findByRole("status")).toHaveTextContent("Account created. Please sign in.");
  });

  it("the old address still works", async () => {
    const { router } = renderApp("/login?next=%2Fbudget", OPTIONS_OFF);
    await screen.findByText("Sign in to your ledger.");
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(router.state.location.search).toBe("?next=%2Fbudget");
  });

  it("after a session ended, signing in lands signed in (nothing of the old session is kept)", async () => {
    renderApp(
      "/sign-in?next=%2Faccounts",
      { ...SIGNED_IN, ...OPTIONS_OFF, "/api/auth/sign-in": [204, null] },
      (queryClient) => {
        // What the cache holds after a refresh found the session gone: the old session and a 401.
        queryClient.setQueryData(["session"], { email: "old@example.com", today: "2026-11-13" });
        queryClient
          .getQueryCache()
          .find({ queryKey: ["session"] })
          ?.setState({ status: "error", error: new ApiError(401, "missing authentication token") });
        queryClient.setQueryData(["accounts"], ["the previous person's accounts"]);
      },
    );
    await signIn();
    expect(await screen.findByRole("heading", { name: "Accounts" })).toBeInTheDocument();
  });
});
