// What every screen that signs a person in does next.
import type { QueryClient } from "@tanstack/react-query";

/** A new session starts from nothing: every cached answer belonged to the session before (an ended one, or another
 * person on this device), and the old session's 401 must not send the new one back to sign in. */
export function forgetPreviousSession(queryClient: QueryClient): void {
  queryClient.removeQueries();
}
