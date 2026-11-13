// Renders the app's routes in memory against a stubbed API: no network, a fresh cache, no retries.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";

import { makeClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { routes } from "../app/router";

/** An answer per path: [status, JSON body], or an Error to fail as a lost connection does. */
export type Answers = Record<string, [number, unknown] | Error>;

export const SIGNED_IN: Answers = {
  "/api/auth/session": [
    200,
    { email: "ada@example.com", today: "2026-11-13", feedback_url: null, can_delete_login: false },
  ],
};

export function stubClient(answers: Answers) {
  const fetch = vi.fn((request: Request) => {
    const answer = answers[new URL(request.url).pathname];
    if (answer instanceof Error) return Promise.reject(answer);
    const [status, body] = answer ?? [404, { detail: "Not Found" }];
    return Promise.resolve(
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
    );
  });
  return makeClient({
    baseUrl: "http://localhost",
    fetch: fetch as unknown as typeof globalThis.fetch,
    onUnauthorized: vi.fn(),
  });
}

export function renderApp(path: string, answers: Answers = SIGNED_IN) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <ApiProvider client={stubClient(answers)}>
        <RouterProvider router={router} />
      </ApiProvider>
    </QueryClientProvider>,
  );
  return { router, queryClient };
}
