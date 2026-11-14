import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type Answers, calledPaths, renderApp, SIGNED_IN } from "../../test/render";

const ON: Answers = { "/api/auth/options": [200, { signup_enabled: false, reset_enabled: true, test_notice: false }] };

async function choose(password = "correct horse", confirm = password) {
  await userEvent.type(await screen.findByLabelText("New password"), password);
  await userEvent.type(screen.getByLabelText("Confirm password"), confirm);
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
}

describe("choosing a new password", () => {
  it("opening the link sends nothing, so a mail scanner cannot spend it", async () => {
    const { fetch } = renderApp("/reset?token_hash=abc", ON);
    expect(await screen.findByText("Choose a new password.")).toBeInTheDocument();
    expect(calledPaths(fetch)).toEqual(["/api/auth/options"]);
  });

  it("a link without its token goes to forgot with a message", async () => {
    const { router } = renderApp("/reset", ON);
    expect(await screen.findByRole("alert")).toHaveTextContent("That link is not valid. Ask for a new one.");
    expect(router.state.location.pathname).toBe("/forgot");
  });

  it("a spent link goes to forgot with the server's message", async () => {
    const spent = "That link has expired or was already used. Ask for a new one.";
    const { router } = renderApp("/reset?token_hash=abc", {
      ...ON,
      "/api/auth/reset": [400, { detail: { message: spent, code: "link-invalid" } }],
    });
    await choose();
    expect(await screen.findByRole("alert")).toHaveTextContent(spent);
    expect(router.state.location.pathname).toBe("/forgot");
  });

  it("mismatched passwords are caught before sending", async () => {
    const { fetch } = renderApp("/reset?token_hash=abc", ON);
    await choose("correct horse", "another horse");
    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(calledPaths(fetch)).not.toContain("/api/auth/reset");
  });

  it("success goes Home with the toast", async () => {
    renderApp("/reset?token_hash=abc", { ...SIGNED_IN, ...ON, "/api/auth/reset": [204, null] });
    await choose();
    expect(await screen.findByRole("heading", { name: "Home" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Your password was changed. You are signed in.");
  });

  it("is not offered when reset is off", async () => {
    const { router } = renderApp("/reset?token_hash=abc", {
      "/api/auth/options": [200, { signup_enabled: false, reset_enabled: false, test_notice: false }],
    });
    await screen.findByText("Sign in to your ledger.");
    expect(router.state.location.pathname).toBe("/sign-in");
  });

  it("when the server's options cannot be loaded, the link is kept and the screen says why", async () => {
    const { router } = renderApp("/reset?token_hash=abc", { "/api/auth/options": new TypeError("Failed to fetch") });
    expect(await screen.findByRole("alert")).toHaveTextContent("finode can't be reached. Check your connection.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(router.state.location.search).toBe("?token_hash=abc");
  });

  it("two quick submits send the new password once", async () => {
    const { fetch } = renderApp("/reset?token_hash=abc", { ...ON, "/api/auth/reset": "never" });
    await userEvent.type(await screen.findByLabelText("New password"), "correct horse");
    await userEvent.type(screen.getByLabelText("Confirm password"), "correct horse");
    const form = screen.getByRole("button", { name: "Change password" }).closest("form");
    if (!form) throw new Error("no form");
    fireEvent.submit(form);
    fireEvent.submit(form);
    await vi.waitFor(() => {
      expect(calledPaths(fetch)).toContain("/api/auth/reset");
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(calledPaths(fetch).filter((p) => p === "/api/auth/reset")).toHaveLength(1);
  });
});
