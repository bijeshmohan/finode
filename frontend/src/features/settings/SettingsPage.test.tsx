import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";

const PROFILE = { first_name: "Ada", last_name: "Lovelace", default_currency: "INR" };
const BASE: Answers = {
  ...SIGNED_IN,
  "/api/profile/": [200, PROFILE],
  "/api/profile/currencies": [
    200,
    [
      { code: "INR", name: "Indian rupee", decimals: 2 },
      { code: "USD", name: "US dollar", decimals: 2 },
    ],
  ],
  "/api/auth/options": [200, { signup_enabled: false, reset_enabled: false, test_notice: false }],
};

function open(more: Answers = {}, path = "/settings") {
  return renderApp(path, { ...BASE, ...more });
}

function row(name: RegExp | string) {
  return screen.getByRole("button", { name });
}

async function sent(fetch: ReturnType<typeof renderApp>["fetch"], method: string, path: string) {
  await waitFor(() => {
    expect(fetch.mock.calls.some(([r]) => r.method === method && new URL(r.url).pathname === path)).toBe(true);
  });
  const call = fetch.mock.calls.find(([r]) => r.method === method && new URL(r.url).pathname === path);
  if (!call) throw new Error("nothing sent");
  const text = await call[0].clone().text();
  return (text ? JSON.parse(text) : {}) as Record<string, unknown>;
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("Settings", () => {
  it("lists each row with its value", async () => {
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /^Ada Lovelace/ })).toHaveTextContent("ada@example.com");
    expect(row(/^Currency/)).toHaveTextContent("INR");
    expect(row(/^Appearance/)).toHaveTextContent("Match device");
    const links: [string, string][] = [
      ["Backup, export and import", "/profile/data"],
      ["Tags", "/tags"],
      ["People", "/people"],
      ["Recurring transactions", "/recurring"],
      ["AI assistants", "/profile/assistants"],
    ];
    for (const [name, href] of links) {
      expect(within(screen.getByRole("main")).getByRole("link", { name })).toHaveAttribute("href", href);
    }
    expect(screen.queryByRole("link", { name: "Send feedback" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /About this test/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("with no name the row is your profile", async () => {
    open({ "/api/profile/": [200, { first_name: null, last_name: null, default_currency: "INR" }] });
    expect(await screen.findByRole("button", { name: /^Your profile/ })).toBeInTheDocument();
  });

  it("saves the name", async () => {
    const { fetch } = open();
    await userEvent.click(await screen.findByRole("button", { name: /^Ada Lovelace/ }));
    expect(
      screen.getByText("Your email (ada@example.com) is used to sign in and can't be changed here."),
    ).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("First name"));
    await userEvent.type(screen.getByLabelText("First name"), "Augusta");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    expect(await sent(fetch, "PATCH", "/api/profile/")).toEqual({ first_name: "Augusta", last_name: "Lovelace" });
    expect(await screen.findByText("Profile saved")).toBeInTheDocument();
  });

  it("saves the currency and every amount follows", async () => {
    let currency = "INR";
    const { fetch } = open({
      "/api/profile/": () => [200, { ...PROFILE, default_currency: currency }],
    });
    await userEvent.click(await screen.findByRole("button", { name: /^Currency/ }));
    expect(screen.getByText("Changing it only changes the label: nothing is converted.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Currency"), "USD");
    currency = "USD";
    await userEvent.click(screen.getByRole("button", { name: "Save currency" }));
    expect(await sent(fetch, "PATCH", "/api/profile/")).toEqual({ default_currency: "USD" });
    expect(await screen.findByText("Currency saved")).toBeInTheDocument();
    await waitFor(() => {
      expect(row(/^Currency/)).toHaveTextContent("USD");
    });
  });

  it("the address opens a row", async () => {
    open({}, "/settings#currency");
    expect(await screen.findByLabelText("Currency")).toBeInTheDocument();
    expect(row(/^Currency/)).toHaveAttribute("aria-expanded", "true");
  });

  it("chooses the appearance for this browser", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: /^Appearance/ }));
    expect(screen.getByText("Applies to this browser only.")).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Theme" });
    expect(within(group).getByRole("button", { name: "Match device" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(group).getByRole("button", { name: "Dark" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(within(group).getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
    expect(row(/^Appearance/)).toHaveTextContent("Dark");
    await userEvent.click(within(group).getByRole("button", { name: "Match device" }));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("offers feedback and the test notice only when the server has them", async () => {
    open({
      "/api/auth/session": [
        200,
        {
          email: "ada@example.com",
          today: "2026-11-13",
          feedback_url: "https://forms.example/f",
          can_delete_login: false,
        },
      ],
      "/api/auth/options": [200, { signup_enabled: false, reset_enabled: false, test_notice: true }],
    });
    expect(await screen.findByRole("link", { name: "Send feedback" })).toHaveAttribute(
      "href",
      "https://forms.example/f",
    );
    await userEvent.click(await screen.findByRole("button", { name: /^About this test/ }));
    expect(screen.getByText("This is a test.")).toBeInTheDocument();
  });

  it("signs out to the sign-in screen", async () => {
    const { fetch, router, queryClient } = open({ "/api/auth/sign-out": [204, null] });
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await sent(fetch, "POST", "/api/auth/sign-out");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/sign-in");
    });
    await waitFor(() => {
      expect(queryClient.getQueryData(["profile"])).toBeUndefined();
    });
  });
});
