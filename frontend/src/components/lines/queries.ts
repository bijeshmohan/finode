// What the shared rows (Lines) and their pickers read and make: the pickers' groups, where a new account or category can
// go, and making one from the picker's "＋ New". Every view is refreshed after, so the pickers list it.
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../../api/views";

export type PickGroup = components["schemas"]["PickGroupRead"];
export type PickOption = components["schemas"]["PickOptionRead"];
export type FormRow = components["schemas"]["FormRow"];
export type ParentOption = components["schemas"]["ParentOption"];
export type CategoryParent = components["schemas"]["CategoryParent"];

/** Make an account or a category from a picker's "＋ New"; every view is refreshed, so the pickers list it. */
export function useAddAccount() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: components["schemas"]["AccountCreate"]) => data(api.POST("/api/accounts/", { body })),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: VIEWS });
    },
  });
}

export function useAddCategory() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: components["schemas"]["CategoryCreate"]) => data(api.POST("/api/categories/", { body })),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: VIEWS });
    },
  });
}
