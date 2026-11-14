// What the sign-in screens offer on this server (sign-up, forgotten password, the test notice).
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { AuthScreen } from "./AuthScreen";
import { FormError } from "./fields";
import { UNREACHABLE } from "../../api/messages";

export type AuthOptions = components["schemas"]["AuthOptions"];

export function useAuthOptions() {
  const api = useApi();
  return useQuery({
    queryKey: ["auth-options"],
    queryFn: () => data(api.GET("/api/auth/options")),
    staleTime: Infinity,
  });
}

/** A screen that depends on what the server offers. If that cannot be learnt, it says so and offers to try again,
 * keeping the address (a reset link is not thrown away). */
export function WithOptions({ children }: { children: (options: AuthOptions) => ReactNode }) {
  const options = useAuthOptions();
  if (options.isPending) return null;
  if (options.isError) {
    return (
      <AuthScreen>
        <FormError message={UNREACHABLE} />
        <button type="button" onClick={() => void options.refetch()}>
          Try again
        </button>
      </AuthScreen>
    );
  }
  return children(options.data);
}
