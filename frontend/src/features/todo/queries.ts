// The to-do bell's server data: what needs a decision now, and its two fixes that stay in the sheet (a category for a
// payment, an account into the budget). Every change refreshes all views, the bell's count with them.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../../api/views";

export type TodoView = components["schemas"]["TodoView"];

export function useTodo() {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "todo"],
    queryFn: () => data(api.GET("/api/views/todo")),
  });
}

function useRefresh() {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: VIEWS });
  };
}

export function useLabelPayment() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ transactionId, categoryId }: { transactionId: string; categoryId: string }) =>
      data(
        api.POST("/api/transactions/{transaction_id}/category", {
          params: { path: { transaction_id: transactionId } },
          body: { category_id: categoryId },
        }),
      ),
    onSuccess: refresh,
  });
}

export function useIncludeAccount() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (accountId: string) =>
      data(api.POST("/api/budget/accounts/{account_id}/include", { params: { path: { account_id: accountId } } })),
    onSuccess: refresh,
  });
}
