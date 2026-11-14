// The Add screen's server data: where the form starts and what its pickers offer, and saving.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

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

export type SharePreviewAsk = components["schemas"]["SharePreviewAsk"];
export type SharePreview = components["schemas"]["SharePreview"];

/** What the Split would do, as typed so far: asked 400 ms after the last change, and not at all without an amount. */
export function useSharePreview(ask: SharePreviewAsk | null) {
  const api = useApi();
  const [asked, setAsked] = useState(ask);
  const wanted = JSON.stringify(ask);
  useEffect(() => {
    const timer = setTimeout(() => {
      setAsked(JSON.parse(wanted) as SharePreviewAsk | null);
    }, 400);
    return () => {
      clearTimeout(timer);
    };
  }, [wanted]);
  return useQuery({
    queryKey: [...VIEWS, "share-preview", asked],
    queryFn: () => {
      if (asked === null) throw new Error("nothing to preview");
      return data(api.POST("/api/views/entry-share-preview", { body: asked }));
    },
    enabled: asked !== null,
    retry: false,
  });
}

export type ParentOption = components["schemas"]["ParentOption"];
export type CategoryParent = components["schemas"]["CategoryParent"];

/** Make an account or a category from the Add screen's picker; every view is refreshed, so the pickers list it. */
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
