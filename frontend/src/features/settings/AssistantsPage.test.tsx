import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type Answers, renderApp, SIGNED_IN } from "../../test/render";

const TOKEN = {
  id: "00000000-0000-4000-8000-000000000601",
  name: "Claude Desktop",
  scope: "read",
  prefix: "fn_ab12",
  created: "2026-11-02T10:00:00Z",
  last_used: null,
  revoked: null,
};
const APP = {
  id: "00000000-0000-4000-8000-000000000602",
  client_name: "Claude",
  scope: "manage",
  created: "2026-11-05T10:00:00Z",
  last_used: "2026-11-13T09:00:00Z",
};
const MCP = "https://api.example.com/mcp/";

function view(over: Record<string, unknown> = {}) {
  return { mcp_url: MCP, tokens: [TOKEN], apps: [APP], ...over };
}

function open(more: Answers = {}, answer: unknown = view()) {
  return renderApp("/profile/assistants", { ...SIGNED_IN, "/api/assistants/": [200, answer], ...more });
}

async function sent(fetch: ReturnType<typeof renderApp>["fetch"], path: string) {
  await waitFor(() => {
    expect(fetch.mock.calls.some(([r]) => new URL(r.url).pathname === path && r.method === "POST")).toBe(true);
  });
  const call = fetch.mock.calls.find(([r]) => new URL(r.url).pathname === path && r.method === "POST");
  const text = call ? await call[0].clone().text() : "";
  return (text ? JSON.parse(text) : {}) as Record<string, unknown>;
}

async function item(name: string) {
  const found = (await screen.findByText(name, { selector: "strong" })).closest("li");
  if (!found) throw new Error(`no ${name}`);
  return found;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AI assistants", () => {
  it("lists what is connected with its access and when it was used", async () => {
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "AI assistants" })).toBeInTheDocument();
    const app = await item("Claude");
    expect(app).toHaveTextContent("read, write & manage accounts");
    expect(app).toHaveTextContent("Signed in · connected Thu, 5 Nov · last used Today");
    expect(within(app).getByRole("button", { name: "Make read only" })).toBeInTheDocument();
    expect(within(app).getByRole("button", { name: "Stop account changes" })).toBeInTheDocument();
    expect(within(app).queryByRole("button", { name: "Allow account changes" })).not.toBeInTheDocument();
    const token = await item("Claude Desktop");
    expect(token).toHaveTextContent("read only");
    expect(token).toHaveTextContent("Token fn_ab12… · created Mon, 2 Nov · never used");
    expect(within(token).getByRole("button", { name: "Allow changes" })).toBeInTheDocument();
    expect(within(token).getByRole("button", { name: "Allow account changes" })).toBeInTheDocument();
  });

  it("with nothing connected says so", async () => {
    open({}, view({ tokens: [], apps: [] }));
    expect(await screen.findByText("Nothing connected yet.")).toBeInTheDocument();
  });

  it("allowing changes asks first and sends the new access", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    const path = `/api/assistants/tokens/${TOKEN.id}/access`;
    const { fetch } = open({ [path]: [200, {}] });
    await userEvent.click(within(await item("Claude Desktop")).getByRole("button", { name: "Allow changes" }));
    expect(ask).toHaveBeenCalledWith("Let assistants using 'Claude Desktop' record, edit and delete transactions?");
    expect(await sent(fetch, path)).toEqual({ scope: "write" });
    expect(await screen.findByText("Access updated. It applies to the very next request.")).toBeInTheDocument();
  });

  it("an app's account changes are stopped without asking", async () => {
    const ask = vi.spyOn(window, "confirm");
    const path = `/api/assistants/apps/${APP.id}/access`;
    const { fetch } = open({ [path]: [200, {}] });
    await userEvent.click(within(await item("Claude")).getByRole("button", { name: "Stop account changes" }));
    expect(await sent(fetch, path)).toEqual({ scope: "write" });
    expect(ask).not.toHaveBeenCalled();
  });

  it("revokes a token and disconnects an app after asking", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    const revoke = `/api/assistants/tokens/${TOKEN.id}/revoke`;
    const disconnect = `/api/assistants/apps/${APP.id}/disconnect`;
    const { fetch } = open({ [revoke]: [200, {}], [disconnect]: [200, {}] });
    await userEvent.click(within(await item("Claude Desktop")).getByRole("button", { name: "Revoke" }));
    expect(ask).toHaveBeenCalledWith("Revoke 'Claude Desktop'? Assistants using it stop working at once.");
    await sent(fetch, revoke);
    expect(await screen.findByText("Token revoked. Assistants using it can no longer connect.")).toBeInTheDocument();
    await userEvent.click(within(await item("Claude")).getByRole("button", { name: "Disconnect" }));
    expect(ask).toHaveBeenCalledWith("Disconnect Claude? It stops working at once.");
    await sent(fetch, disconnect);
    expect(await screen.findByText("App disconnected. It can no longer reach your books.")).toBeInTheDocument();
  });

  it("offers the address to sign in with Claude", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: /^Sign in with Claude/ }));
    expect(
      screen.getByText(
        "Add this address as a custom connector in Claude or another app, then choose the access level.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText(MCP)[0]).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
  });

  it("creates a token and shows its secret once, with the setup filled in", async () => {
    const created = {
      ...TOKEN,
      id: "00000000-0000-4000-8000-000000000603",
      name: "Cursor",
      scope: "write",
      secret: "fn_secret_123",
    };
    const { fetch, router } = open({ "/api/assistants/tokens": [201, created] });
    await userEvent.click(await screen.findByRole("button", { name: /^Use a token/ }));
    await userEvent.type(screen.getByLabelText("Name"), "Cursor");
    await userEvent.click(screen.getByRole("radio", { name: "Write" }));
    expect(screen.getByText(/^Read & write\./)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create token" }));
    expect(await sent(fetch, "/api/assistants/tokens")).toEqual({ name: "Cursor", scope: "write" });
    expect(await screen.findByRole("heading", { name: "Cursor is ready" })).toBeInTheDocument();
    expect(
      screen.getByText("Copy this token now. finode keeps only a fingerprint of it, so it can't be shown again."),
    ).toBeInTheDocument();
    expect(screen.getAllByText("fn_secret_123").length).toBeGreaterThan(0);
    expect(screen.getByText(/claude mcp add --transport http finode .*Bearer fn_secret_123/)).toBeInTheDocument();
    await router.navigate("/settings");
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    await router.navigate("/profile/assistants");
    await screen.findByRole("heading", { level: 1, name: "AI assistants" });
    expect(screen.queryByText("fn_secret_123")).not.toBeInTheDocument();
  });

  it("the secret is kept nowhere in the app's cache, only on the page", async () => {
    const created = { ...TOKEN, id: "00000000-0000-4000-8000-000000000604", name: "Cursor", secret: "fn_secret_456" };
    const { queryClient } = open({ "/api/assistants/tokens": [201, created] });
    await userEvent.click(await screen.findByRole("button", { name: /^Use a token/ }));
    await userEvent.type(screen.getByLabelText("Name"), "Cursor");
    await userEvent.click(screen.getByRole("button", { name: "Create token" }));
    expect(await screen.findByRole("heading", { name: "Cursor is ready" })).toBeInTheDocument();
    await waitFor(() => {
      const held = JSON.stringify([
        queryClient
          .getMutationCache()
          .getAll()
          .map((m) => m.state),
        queryClient
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data),
      ]);
      expect(held).not.toContain("fn_secret_456");
    });
    expect(screen.getAllByText("fn_secret_456").length).toBeGreaterThan(0);
  });

  it("a refused token name shows the server's words", async () => {
    open({ "/api/assistants/tokens": [400, { detail: "a token needs a name!" }] });
    await userEvent.click(await screen.findByRole("button", { name: /^Use a token/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create token" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("a token needs a name!");
  });

  it("the setup instructions use a placeholder token", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: /^Setup instructions for tokens/ }));
    expect(screen.getByText(/Replace/)).toHaveTextContent("Replace YOUR_TOKEN below with a token you created.");
    expect(screen.getByText(/claude mcp add/)).toHaveTextContent("Bearer YOUR_TOKEN");
  });
});
