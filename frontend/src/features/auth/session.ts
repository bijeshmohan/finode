// What every screen that signs a person in does next.
import { type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useRef } from "react";

/** A new session starts from nothing: every cached answer belonged to the session before (an ended one, or another
 * person on this device), and the old session's 401 must not send the new one back to sign in. */
export function forgetPreviousSession(queryClient: QueryClient): void {
  queryClient.removeQueries();
}

/** Submits a form's mutation once until it settles, however fast the clicks come (a second reset would find the link
 * already spent and override the first one's success). */
export function useSubmitOnce<T>(mutation: UseMutationResult<unknown, unknown, T>): (body: T) => void {
  const sending = useRef(false);
  return (body: T) => {
    if (sending.current) return;
    sending.current = true;
    mutation.mutate(body, {
      onSettled: () => {
        sending.current = false;
      },
    });
  };
}
