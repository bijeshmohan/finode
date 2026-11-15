import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { leaveTo } from "../../app/leave";
import { type Answers, renderApp, SIGNED_IN } from "../../test/render";

const DETAILS = {
  authorization_id: "auth-1",
  client_name: "Claude",
  client_uri: "https://claude.ai",
  redirect_uri: "https://claude.ai/callback",
  scopes: ["openid"],
  redirect_url: null,
};

function open(more: Answers = {}, path = "/oauth/consent?authorization_id=auth-1") {
  return renderApp(path, { ...SIGNED_IN, "/api/oauth/consent/auth-1": [200, DETAILS], ...more });
}

vi.mock("../../app/leave", () => ({ leaveTo: vi.fn() }));

function goes() {
  const leave = vi.mocked(leaveTo);
  leave.mockClear();
  return leave;
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("the consent screen", () => {
  it("asks what the app may do", async () => {
    goes();
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Connect Claude?" })).toBeInTheDocument();
    expect(screen.getByText(/wants to work with your finode books on your behalf/)).toHaveTextContent(
      "Claude wants to work with your finode books on your behalf. (https://claude.ai)",
    );
    expect(screen.getByText(/After you decide/)).toHaveTextContent(
      "After you decide, you'll be sent back to https://claude.ai/callback.",
    );
    expect(screen.getByRole("heading", { name: "What should it be allowed to do?" })).toBeInTheDocument();
    for (const name of ["Allow read only", "Allow read & write", "Allow read, write & manage accounts", "Deny"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByText("Ask: “What did I spend on food in September?”")).toBeInTheDocument();
  });

  /** The details first; the decision's answer (the way back) after. */
  function deciding(): Answers {
    let asked = 0;
    return {
      "/api/oauth/consent/auth-1": () => {
        asked += 1;
        return asked === 1 ? [200, DETAILS] : [200, { redirect_url: "https://claude.ai/callback?code=x" }];
      },
    };
  }

  it("allowing sends the level and goes back to the app", async () => {
    const assign = goes();
    const { fetch } = open(deciding());
    await userEvent.click(await screen.findByRole("button", { name: "Allow read & write" }));
    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith("https://claude.ai/callback?code=x");
    });
    const call = fetch.mock.calls.find(([r]) => r.method === "POST");
    expect(await call?.[0].clone().json()).toEqual({ decision: "allow", access: "write" });
  });

  it("denying goes back too", async () => {
    const assign = goes();
    const { fetch } = open(deciding());
    await userEvent.click(await screen.findByRole("button", { name: "Deny" }));
    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith("https://claude.ai/callback?code=x");
    });
    const call = fetch.mock.calls.find(([r]) => r.method === "POST");
    expect(await call?.[0].clone().json()).toEqual({ decision: "deny", access: "read" });
  });

  it("an app already decided goes straight back", async () => {
    const assign = goes();
    open({ "/api/oauth/consent/auth-1": [200, { ...DETAILS, redirect_url: "https://claude.ai/callback?code=x" }] });
    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith("https://claude.ai/callback?code=x");
    });
  });

  it("without an id it says where to start", async () => {
    goes();
    open({}, "/oauth/consent");
    expect(await screen.findByRole("heading", { level: 1, name: "Can't connect" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This page is opened by an app that wants to connect. Start from the app's connector settings.",
    );
    expect(screen.getAllByRole("link", { name: "AI assistants" }).map((l) => l.getAttribute("href"))).toContain(
      "/profile/assistants",
    );
  });

  it("a refusal says why", async () => {
    goes();
    open({
      "/api/oauth/consent/auth-1": [400, { detail: "The app asked to be opened in a way finode does not allow." }],
    });
    expect(await screen.findByRole("heading", { level: 1, name: "Can't connect" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("in a way finode does not allow");
  });
});
