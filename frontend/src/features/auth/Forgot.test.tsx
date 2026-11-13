import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Answers, renderApp } from "../../test/render";

const ON: Answers = { "/api/auth/options": [200, { signup_enabled: false, reset_enabled: true, test_notice: false }] };

describe("forgotten password", () => {
  it("is not offered when reset is off", async () => {
    const { router } = renderApp("/forgot", {
      "/api/auth/options": [200, { signup_enabled: false, reset_enabled: false, test_notice: false }],
    });
    await screen.findByText("Sign in to your ledger.");
    expect(router.state.location.pathname).toBe("/sign-in");
  });

  it("sending shows the same answer for anyone", async () => {
    renderApp("/forgot", { ...ON, "/api/auth/forgot": [202, null] });
    await userEvent.type(await screen.findByLabelText("Email"), "a@b.co");
    await userEvent.click(screen.getByRole("button", { name: "Send the link" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "If there is an account for a@b.co, an email with a link to choose a new password is on its way. The link works " +
        "for an hour. Check your spam folder if it does not arrive.",
    );
    expect(screen.queryByRole("button", { name: "Send the link" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to sign in" })).toHaveAttribute("href", "/sign-in");
  });

  it("a refusal shows the server's message", async () => {
    renderApp("/forgot", {
      ...ON,
      "/api/auth/forgot": [429, { detail: { message: "Too many attempts. Try again in 3 minutes.", code: null } }],
    });
    await userEvent.type(await screen.findByLabelText("Email"), "a@b.co");
    await userEvent.click(screen.getByRole("button", { name: "Send the link" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts. Try again in 3 minutes.");
  });
});
