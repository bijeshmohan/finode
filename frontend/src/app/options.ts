// What the sign-in screens offer on this server (sign-up, forgotten password, the test notice), also shown on Settings.
import { useQuery } from "@tanstack/react-query";

import { data } from "../api/client";
import { useApi } from "../api/context";
import type { components } from "../api/schema";

export type AuthOptions = components["schemas"]["AuthOptions"];

export function useAuthOptions() {
  const api = useApi();
  return useQuery({
    queryKey: ["auth-options"],
    queryFn: () => data(api.GET("/api/auth/options")),
    staleTime: Infinity,
  });
}
