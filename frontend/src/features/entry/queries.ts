// The Add screen's server data: where the form starts and what its pickers offer, and saving.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components, operations } from "../../api/schema";
import { VIEWS } from "../transactions/queries";

export type EntryFormView = components["schemas"]["EntryFormView"];
export type PickGroup = components["schemas"]["PickGroupRead"];
export type PickOption = components["schemas"]["PickOptionRead"];
export type EntryBody = components["schemas"]["EntryForm"];
export type FormQuery = NonNullable<operations["entry_form_api_views_entry_form_get"]["parameters"]["query"]>;

export function useEntryForm(query: FormQuery) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "entry-form", query],
    queryFn: () => data(api.GET("/api/views/entry-form", { params: { query } })),
    staleTime: 0,
  });
}

/** Save a new entry, or change `transactionId`; every view is refreshed afterwards. */
export function useSaveEntry(transactionId: string | undefined) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: EntryBody) =>
      transactionId
        ? data(api.PUT("/api/entries/{transaction_id}", { params: { path: { transaction_id: transactionId } }, body }))
        : data(api.POST("/api/entries", { body })),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: VIEWS });
    },
  });
}
