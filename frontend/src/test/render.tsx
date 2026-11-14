// Renders the app's routes in memory against a stubbed API: no network, a fresh cache, no retries.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";

import { makeClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { routes } from "../app/router";
import { SessionProvider } from "../app/session";
import { ToastProvider } from "../app/toast";

/** An answer per path: [status, JSON body], an Error to fail as a lost connection does, "never" to keep it waiting, or
 * a function of the request's URL for answers that depend on the query. */
type Answer = [number, unknown] | Error | "never";
export type Answers = Record<string, Answer | ((url: URL) => Answer)>;

export const SIGNED_IN: Answers = {
  "/api/auth/session": [
    200,
    { email: "ada@example.com", today: "2026-11-13", feedback_url: null, can_delete_login: false },
  ],
};

export function stubClient(answers: Answers) {
  const fetch = vi.fn((request: Request) => {
    const url = new URL(request.url);
    const given = answers[url.pathname];
    const answer = typeof given === "function" ? given(url) : given;
    if (answer instanceof Error) return Promise.reject(answer);
    if (answer === "never") return new Promise<Response>(() => undefined);
    const [status, body] = answer ?? [404, { detail: "Not Found" }];
    const empty = status === 204 || status === 202;
    return Promise.resolve(
      new Response(empty ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
    );
  });
  const client = makeClient({
    baseUrl: "http://localhost",
    fetch: fetch as unknown as typeof globalThis.fetch,
    onUnauthorized: vi.fn(),
  });
  return { client, fetch };
}

/** The paths the app called, in order. */
export function calledPaths(fetch: ReturnType<typeof stubClient>["fetch"]): string[] {
  return fetch.mock.calls.map(([request]) => new URL(request.url).pathname);
}

export function renderApp(path: string, answers: Answers = SIGNED_IN, seed?: (queryClient: QueryClient) => void) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  seed?.(queryClient);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const { client, fetch } = stubClient(answers);
  render(
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={client}>
        <RouterProvider router={router} />
      </ApiProvider>
    </QueryClientProvider>,
  );
  return { router, queryClient, fetch };
}

/** One component inside the app's own providers (the session, toasts, a router) against the stubbed API. */
export function renderInApp(ui: ReactNode, answers: Answers = SIGNED_IN) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([
    {
      path: "*",
      element: (
        <SessionProvider>
          <ToastProvider>{ui}</ToastProvider>
        </SessionProvider>
      ),
    },
  ]);
  const { client, fetch } = stubClient(answers);
  render(
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={client}>
        <RouterProvider router={router} />
      </ApiProvider>
    </QueryClientProvider>,
  );
  return { router, queryClient, fetch };
}
