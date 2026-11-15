// The Recurring pages' server data: the list, where the form starts, saving a rule from its rows, and pausing,
// resuming, skipping and deleting one. Every change refreshes all views.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../../api/views";

export type RecurringView = components["schemas"]["RecurringView"];
export type RuleRow = components["schemas"]["RuleRowRead"];
export type RecurringFormView = components["schemas"]["RecurringFormView"];
export type RuleBody = components["schemas"]["RecurringForm"];

export function useRecurringList() {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "recurring"],
    queryFn: () => data(api.GET("/api/views/recurring")),
  });
}

export function useRecurringForm(recurringId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "recurring-form", recurringId ?? ""],
    queryFn: () =>
      data(
        api.GET("/api/views/recurring-form", { params: { query: recurringId ? { recurring_id: recurringId } : {} } }),
      ),
    staleTime: 0,
  });
}

function useRefresh() {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: VIEWS });
  };
}

/** Save a new rule, or change `recurringId`, from the form's rows. */
export function useSaveRule(recurringId: string | undefined) {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: RuleBody) =>
      recurringId
        ? data(api.PUT("/api/recurring/{recurring_id}/form", { params: { path: { recurring_id: recurringId } }, body }))
        : data(api.POST("/api/recurring/form", { body })),
    onSuccess: refresh,
  });
}

export type RuleAction = "pause" | "resume" | "skip" | "delete";

export function useRuleAction(recurringId: string) {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (action: RuleAction) => {
      const path = { recurring_id: recurringId };
      if (action === "delete") return data(api.DELETE("/api/recurring/{recurring_id}", { params: { path } }));
      if (action === "pause") return data(api.POST("/api/recurring/{recurring_id}/pause", { params: { path } }));
      if (action === "resume") return data(api.POST("/api/recurring/{recurring_id}/resume", { params: { path } }));
      return data(api.POST("/api/recurring/{recurring_id}/skip", { params: { path } }));
    },
    onSuccess: refresh,
  });
}
