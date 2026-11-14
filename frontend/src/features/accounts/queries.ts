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

export type AccountFormView = components["schemas"]["AccountFormView"];
export type KindChoice = components["schemas"]["KindChoiceRead"];
export type AccountCreate = components["schemas"]["AccountCreate"];
export type AccountUpdate = components["schemas"]["AccountUpdate"];

/** Where the account form starts: `account_id` to edit, otherwise opened for a kind (`parent`) or a type (`root`). */
export function useAccountForm(query: { account_id?: string; parent?: string; root?: string }) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "account-form", query],
    queryFn: () => data(api.GET("/api/views/account-form", { params: { query } })),
    staleTime: 0,
  });
}

function useRefresh() {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: VIEWS });
  };
}

export function useAddAccountFromForm() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: AccountCreate) => data(api.POST("/api/accounts/", { body })),
    onSuccess: refresh,
  });
}

export function useUpdateAccount(id: string) {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: AccountUpdate) =>
      data(api.PATCH("/api/accounts/{account_id}", { params: { path: { account_id: id } }, body })),
    onSuccess: refresh,
  });
}

export function useDeleteAccount(id: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => data(api.DELETE("/api/accounts/{account_id}", { params: { path: { account_id: id } } })),
    onSuccess: async () => {
      // The account is gone: its own views are dropped, not asked for again (that would answer "not found").
      queryClient.removeQueries({ queryKey: [...VIEWS, "account", id] });
      queryClient.removeQueries({ queryKey: [...VIEWS, "account-form"] });
      await queryClient.invalidateQueries({ queryKey: VIEWS });
    },
  });
}

export function useAddGroup() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: components["schemas"]["GroupCreate"]) => data(api.POST("/api/accounts/groups", { body })),
    onSuccess: refresh,
  });
}
