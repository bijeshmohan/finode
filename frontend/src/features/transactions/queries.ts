// The Transactions screens' server data: a month's list a page at a time, one entry's details, and deleting.
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import { VIEWS } from "../../api/views";
import type { components } from "../../api/schema";
import { useToast } from "../../app/toast";

export type Row = components["schemas"]["RowRead"];
export type DayTotal = components["schemas"]["DayTotal"];
export type Details = components["schemas"]["TransactionDetails"];
export type TransactionsView = components["schemas"]["TransactionsView"];

/** What the list is narrowed to, as the address holds it. */
export interface ListFilters {
  month?: string;
  account?: string;
  category?: string;
  merchant?: string;
  tag?: string;
  q?: string;
  kind?: string;
}

/** How many entries a page of the list asks for (a page can hold more: a day is never split). */
export const PAGE_SIZE = 25;

export function useTransactionsPages(filters: ListFilters) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: [...VIEWS, "transactions", filters],
    queryFn: ({ pageParam }) =>
      data(
        api.GET("/api/views/transactions", {
          params: { query: { ...filters, offset: pageParam, limit: PAGE_SIZE } },
        }),
      ),
    initialPageParam: 0,
    // A page holds whole days: the next one starts after the rows already shown.
    getNextPageParam: (last, pages) => {
      const shown = pages.reduce((n, page) => n + page.rows.length, 0);
      return shown < last.total && last.rows.length > 0 ? shown : undefined;
    },
    // Another month or filter shows the last answer until the new one is in (no flash of "No transactions", and the
    // filters the page shows stay those in use).
    placeholderData: keepPreviousData,
  });
}

export function useTransactionDetails(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "transaction", id],
    queryFn: () =>
      data(api.GET("/api/views/transactions/{transaction_id}", { params: { path: { transaction_id: id } } })),
  });
}

export function useDeleteTransaction() {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (id: string) =>
      data(api.DELETE("/api/transactions/{transaction_id}", { params: { path: { transaction_id: id } } })),
    onSuccess: async (_answer, id) => {
      toast("Transaction deleted");
      // The deleted entry's own details are gone: dropped, not asked for again (that would answer "not found").
      queryClient.removeQueries({ queryKey: [...VIEWS, "transaction", id] });
      // Nor is its edit screen's view asked for again: a "not found" there would swap the screen for the error before
      // it can go back, however long the other views take to refresh.
      const editing = (key: readonly unknown[]) =>
        key[1] === "entry-form" && (key[2] as { transaction_id?: string } | undefined)?.transaction_id === id;
      await queryClient.invalidateQueries({ queryKey: VIEWS, predicate: (query) => !editing(query.queryKey) });
    },
  });
}
