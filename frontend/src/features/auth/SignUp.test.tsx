import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, calledPaths, renderApp, SIGNED_IN } from "../../test/render";

const ON: Answers = { "/api/auth/options": [200, { signup_enabled: true, reset_enabled: false, test_notice: false }] };
const WITH_NOTICE: Answers = {
  "/api/auth/options": [200, { signup_enabled: true, reset_enabled: false, test_notice: true }],
};

async function fill({ confirm = "correct horse", code = "a-long-enough-invite-code" } = {}) {
  await userEvent.type(await screen.findByLabelText("Email"), "new@example.com");
  await userEvent.type(screen.getByLabelText("Password"), "correct horse");
  await userEvent.type(screen.getByLabelText("Confirm password"), confirm);
  await userEvent.type(screen.getByLabelText("Invite code"), code);
}

const create = () => userEvent.click(screen.getByRole("button", { name: "Create account" }));

describe("signing up", () => {
  it("is not offered when sign-up is off", async () => {
    const { router } = renderApp("/sign-up", {
      "/api/auth/options": [200, { signup_enabled: false, reset_enabled: false, test_notice: false }],
    });
    expect(await screen.findByText("Sign in to your ledger.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
  });

  it("shows today's words", async () => {
    renderApp("/sign-up", ON);
    expect(await screen.findByText("Create an account. You need an invite code.")).toBeInTheDocument();
    expect(screen.getByLabelText("Invite code")).toHaveAttribute("type", "password");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  });

  it("mismatched passwords are caught before sending", async () => {
    const { fetch } = renderApp("/sign-up", ON);
    await fill({ confirm: "another horse" });
    await create();
    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(calledPaths(fetch)).not.toContain("/api/auth/sign-up");
  });

  it("a short password is caught before sending", async () => {
    const { fetch } = renderApp("/sign-up", ON);
    await userEvent.type(await screen.findByLabelText("Email"), "new@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await create();
    expect(await screen.findByText("Password must be at least 8 characters.")).toBeInTheDocument();
    expect(calledPaths(fetch)).not.toContain("/api/auth/sign-up");
  });

  it("the test notice asks for the tick", async () => {
    const { fetch } = renderApp("/sign-up", WITH_NOTICE);
    expect(await screen.findByRole("note")).toHaveTextContent("This is a test.");
    await fill();
    await create();
    expect(await screen.findByText("Please read the notice and tick the box to continue.")).toBeInTheDocument();
    expect(calledPaths(fetch)).not.toContain("/api/auth/sign-up");
  });

  it("a wrong invite code shows the server's message", async () => {
    renderApp("/sign-up", {
      ...ON,
      "/api/auth/sign-up": [403, { detail: { message: "Invalid invite code.", code: null } }],
    });
    await fill({ code: "nope" });
    await create();
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid invite code.");
  });

  it("made but not signed in goes to sign in with the notice", async () => {
    renderApp("/sign-up", { ...ON, "/api/auth/sign-up": [201, { signed_in: false }] });
    await fill();
    await create();
    expect(await screen.findByRole("status")).toHaveTextContent("Account created. Please sign in.");
  });

  it("signed in goes Home", async () => {
    renderApp("/sign-up", { ...SIGNED_IN, ...ON, "/api/auth/sign-up": [201, { signed_in: true }] });
    await fill();
    await create();
    expect(await screen.findByRole("heading", { name: "Home" })).toBeInTheDocument();
  });

  it("a 404 from the server sends you to sign in", async () => {
    const { router } = renderApp("/sign-up", { ...ON, "/api/auth/sign-up": [404, { detail: "Not Found" }] });
    await fill();
    await create();
    expect(await screen.findByText("Sign in to your ledger.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
  });

  it("the old address still works", async () => {
    const { router } = renderApp("/signup", ON);
    await screen.findByText("Create an account. You need an invite code.");
    expect(router.state.location.pathname).toBe("/sign-up");
  });
});
