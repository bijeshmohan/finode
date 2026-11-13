// Server data lives in TanStack Query: cached screens show at once and refresh in the background.
import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./client";

/** A refusal (4xx) will be refused again: only a server failure or a lost connection is worth another try. */
export function retry(failures: number, error: Error): boolean {
  if (error instanceof ApiError && error.status < 500) return false;
  return failures < 2;
}

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry } },
});
