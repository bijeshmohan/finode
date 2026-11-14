// One submit of a form's mutation at a time, however fast the clicks come.
import type { UseMutationResult } from "@tanstack/react-query";
import { useRef } from "react";

/** Submits a form's mutation once until it settles, however fast the clicks come (a second reset would find the link
 * already spent and override the first one's success; a second Save would record the entry twice). */
export function useSubmitOnce<TData, TBody>(
  mutation: UseMutationResult<TData, unknown, TBody>,
): (body: TBody, options?: { onSuccess?: (answer: TData) => void }) => void {
  const sending = useRef(false);
  return (body, options) => {
    if (sending.current) return;
    sending.current = true;
    mutation.mutate(body, {
      onSuccess: (answer) => options?.onSuccess?.(answer),
      onSettled: () => {
        sending.current = false;
      },
    });
  };
}
