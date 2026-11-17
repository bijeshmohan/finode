// The Budgets area's server data: the Budgets page and a group's page for a month, the categories money can move
// between, what is coming up, and the changes (assign, a group's own budget, copy, move). Every change refreshes all
// views.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../../api/views";

export type BudgetView = components["schemas"]["BudgetView"];
export type BudgetRow = components["schemas"]["BudgetRowRead"];
export type BudgetGroupView = components["schemas"]["BudgetGroupView"];
export type BudgetMoveView = components["schemas"]["BudgetMoveView"];
export type ComingUpView = components["schemas"]["ComingUpView"];

/** The first day of a `YYYY-MM` month, as the budget routes take it. */
export const firstOf = (month: string) => `${month}-01`;

export function useBudget(month: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "budget", month ?? ""],
    queryFn: () => data(api.GET("/api/views/budget", { params: { query: month ? { month } : {} } })),
  });
}

export function useBudgetGroup(id: string, month: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "budget-group", id, month ?? ""],
    queryFn: () =>
      data(
        api.GET("/api/views/budget/groups/{category_id}", {
          params: { path: { category_id: id }, query: month ? { month } : {} },
        }),
      ),
  });
}

export function useBudgetMove(month: string | null, source: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "budget-move", month ?? "", source ?? ""],
    queryFn: () =>
      data(
        api.GET("/api/views/budget-move", {
          params: { query: { ...(month ? { month } : {}), ...(source ? { source } : {}) } },
        }),
      ),
  });
}

/** What is coming up this month (the line in the sum behind Ready to assign). */
export function useComingUp(enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "coming-up"],
    queryFn: () => data(api.GET("/api/budget/coming-up")),
    enabled,
  });
}

/** The Coming up list: what is coming up this month, by day. */
export function useComingDays() {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "coming-days"],
    queryFn: () => data(api.GET("/api/views/coming-up")),
  });
}

function useRefresh() {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: VIEWS });
  };
}

export function useAssign() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, month, amount }: { id: string; month: string; amount: string }) =>
      data(
        api.PUT("/api/budget/categories/{category_id}", {
          params: { path: { category_id: id } },
          body: { month: firstOf(month), amount },
        }),
      ),
    onSuccess: refresh,
  });
}

export function useAssignGroup() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, month, total }: { id: string; month: string; total: string }) =>
      data(
        api.PUT("/api/budget/groups/{category_id}", {
          params: { path: { category_id: id } },
          body: { month: firstOf(month), total },
        }),
      ),
    onSuccess: refresh,
  });
}

export function useCopyLastMonth() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (month: string) => data(api.POST("/api/budget/copy", { body: { month: firstOf(month) } })),
    onSuccess: refresh,
  });
}

export function useMoveMoney() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: { month: string; from_category: string; to_category: string; amount: string }) =>
      data(api.POST("/api/budget/move", { body: { ...body, month: firstOf(body.month) } })),
    onSuccess: refresh,
  });
}
