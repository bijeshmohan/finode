// The one way the app talks to the API: typed from FastAPI's schema (schema.d.ts), with the session cookie and the
// X-Finode header the API asks of every change (see docs/architecture/mcp-and-auth.md, "Cookie sessions on /api").
import createClient, { type Client, type Middleware } from "openapi-fetch";

import type { paths } from "./schema";

export const API_HEADER = { "X-Finode": "1" } as const;

export type ApiClient = Client<paths>;

export function makeClient(options: { baseUrl: string; fetch?: typeof fetch; onUnauthorized: () => void }): ApiClient {
  const client = createClient<paths>({
    baseUrl: options.baseUrl,
    credentials: "include",
    headers: API_HEADER,
    ...(options.fetch ? { fetch: options.fetch } : {}),
  });
  // A 401 from any other call means the session ended: go and sign in. /api/auth answers for itself (a wrong password
  // is a 401 too, and the session's own 401 is SessionProvider's to handle).
  const signedOut: Middleware = {
    onResponse({ request, response }) {
      const ownAnswer = new URL(request.url).pathname.startsWith("/api/auth/");
      if (response.status === 401 && !ownAnswer) options.onUnauthorized();
      return response;
    },
  };
  client.use(signedOut);
  return client;
}

/** The server answered with an error: its HTTP status and the `detail` of its JSON body. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `the server answered ${String(status)}`);
    this.name = "ApiError";
  }
}

/** The body of a successful call, or an ApiError: what a TanStack Query `queryFn` or `mutationFn` returns. */
export async function data<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data: body, error, response } = await call;
  if (!response.ok) {
    const detail = error && typeof error === "object" && "detail" in error ? error.detail : error;
    throw new ApiError(response.status, detail);
  }
  return body as T;
}

function goToSignIn(): void {
  if (window.location.pathname === "/sign-in") return;
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/sign-in?next=${encodeURIComponent(next)}`);
}

export const api = makeClient({ baseUrl: import.meta.env.VITE_API_URL ?? "", onUnauthorized: goToSignIn });
