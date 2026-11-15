// The People pages' server data: the list, a person's page and one of their entries, and the changes (reversing an
// entry, archiving, restoring, removing, adding and editing a person, an opening balance). Every change refreshes all
// views.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../../api/views";

export type PeopleView = components["schemas"]["PeopleView"];
export type PersonView = components["schemas"]["PersonView"];
export type PersonEntryView = components["schemas"]["PersonEntryView"];
export type Show = PeopleView["show"];

export function usePeople(show: Show) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "people", show],
    queryFn: () => data(api.GET("/api/views/people", { params: { query: { show } } })),
  });
}

export function usePerson(contactId: string) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "person", contactId],
    queryFn: () => data(api.GET("/api/views/people/{contact_id}", { params: { path: { contact_id: contactId } } })),
  });
}

export function usePersonEntry(contactId: string, transactionId: string) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "person-entry", contactId, transactionId],
    queryFn: () =>
      data(
        api.GET("/api/views/people/{contact_id}/entries/{transaction_id}", {
          params: { path: { contact_id: contactId, transaction_id: transactionId } },
        }),
      ),
  });
}

/** Refresh every view, but not `skip` (a view whose subject is gone: asking again would answer "not found"). */
function useRefresh() {
  const queryClient = useQueryClient();
  return async (skip?: readonly unknown[]) => {
    const gone = (key: readonly unknown[]) => skip?.every((part, i) => key[i] === part) ?? false;
    await queryClient.invalidateQueries({ queryKey: VIEWS, predicate: (query) => !gone(query.queryKey) });
  };
}

export function useReverseEntry(contactId: string) {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (transactionId: string) =>
      data(
        api.POST("/api/contacts/{contact_id}/entries/{transaction_id}/reverse", {
          params: { path: { contact_id: contactId, transaction_id: transactionId } },
        }),
      ),
    onSuccess: (_answer, transactionId) => refresh([...VIEWS, "person-entry", contactId, transactionId]),
  });
}

export type PersonAction = "archive" | "restore" | "remove";

export function usePersonAction(contactId: string) {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (action: PersonAction): Promise<"deleted" | "archived" | "restored"> => {
      const path = { contact_id: contactId };
      if (action === "remove") {
        const done = await data(api.DELETE("/api/contacts/{contact_id}", { params: { path } }));
        return done.outcome;
      }
      if (action === "archive") {
        await data(api.POST("/api/contacts/{contact_id}/archive", { params: { path } }));
        return "archived";
      }
      await data(api.POST("/api/contacts/{contact_id}/restore", { params: { path } }));
      return "restored";
    },
    // A removed person's page is not asked for again (it would answer "not found" before the list opens).
    onSuccess: (outcome) => refresh(outcome === "deleted" ? [...VIEWS, "person", contactId] : undefined),
  });
}
