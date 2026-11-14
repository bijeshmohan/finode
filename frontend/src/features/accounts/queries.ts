// The Accounts area's server data: the Accounts page (/api/views/accounts), an account's page a chunk of entries at a
// time (/api/views/accounts/{id}?offset=), and what its menu does. Every change refreshes all views.
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../transactions/queries";

export type AccountsView = components["schemas"]["AccountsView"];
export type AccountView = components["schemas"]["AccountView"];
export type AccountCardData = components["schemas"]["AccountCard"];

export function useAccounts() {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "accounts"],
    queryFn: () => data(api.GET("/api/views/accounts")),
  });
}

/** An account's page: the first chunk carries the page; each "Load more" fetches the next chunk of its entries. */
export function useAccount(id: string) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: [...VIEWS, "account", id],
    queryFn: ({ pageParam }) =>
      data(
        api.GET("/api/views/accounts/{account_id}", {
          params: { path: { account_id: id }, query: { offset: pageParam } },
        }),
      ),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.has_more ? last.next_offset : undefined),
  });
}

/** Pin, unpin, close or reopen an account; every view is refreshed afterwards. */
export function useAccountAction() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "pin" | "unpin" | "close" | "reopen" }) => {
      const path = { params: { path: { account_id: id } } };
      if (action === "pin" || action === "unpin")
        return data(api.PATCH("/api/accounts/{account_id}", { ...path, body: { pinned: action === "pin" } }));
      if (action === "close") return data(api.POST("/api/accounts/{account_id}/close", path));
      return data(api.POST("/api/accounts/{account_id}/reopen", path));
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: VIEWS });
    },
  });
}
