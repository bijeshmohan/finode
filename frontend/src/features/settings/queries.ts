// Settings' changes: the profile (name and currency) and signing out. The currency changes every amount, so the profile and every view refresh.
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../../api/views";

export type ProfileUpdate = components["schemas"]["ProfileUpdate"];

export function useUpdateProfile() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ProfileUpdate) => data(api.PATCH("/api/profile/", { body })),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["profile"] }),
        queryClient.invalidateQueries({ queryKey: VIEWS }),
      ]);
    },
  });
}

export function useSignOut() {
  const api = useApi();
  return useMutation({ mutationFn: () => data(api.POST("/api/auth/sign-out")) });
}
