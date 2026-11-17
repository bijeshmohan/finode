// A screen that depends on what the server offers (app/options.ts).
import type { ReactNode } from "react";

import { type AuthOptions, useAuthOptions } from "../../app/options";
import { AuthScreen } from "./AuthScreen";
import { FormError } from "./fields";
import { UNREACHABLE } from "../../api/messages";

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
