// The AI assistants page's server data: the address assistants connect to, the tokens and the connected apps, and
// the changes (a new token, another access, revoking or disconnecting). The list refreshes after each.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../../api/views";

export type Assistants = components["schemas"]["AssistantsRead"];
export type Token = components["schemas"]["ApiTokenRead"];
export type App = components["schemas"]["ConnectedAppRead"];
export type Scope = "read" | "write" | "manage";

const KEY = [...VIEWS, "assistants"];

export function useAssistants() {
  const api = useApi();
  return useQuery({ queryKey: KEY, queryFn: () => data(api.GET("/api/assistants/")) });
}

function useRefresh() {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: KEY });
  };
}

/** A new token. Its secret is in this answer only: the page takes it and resets the mutation, and with no time kept
 * the client lets the answer go at once, so the secret stays in no cache. */
export function useCreateToken() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: { name: string; scope: Scope }) => data(api.POST("/api/assistants/tokens", { body })),
    onSuccess: refresh,
    gcTime: 0,
  });
}

export type Change =
  | { what: "token"; id: string; scope: Scope }
  | { what: "app"; id: string; scope: Scope }
  | { what: "revoke"; id: string }
  | { what: "disconnect"; id: string };

export function useAssistantChange() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (change: Change): Promise<void> => {
      if (change.what === "token") {
        await data(
          api.POST("/api/assistants/tokens/{token_id}/access", {
            params: { path: { token_id: change.id } },
            body: { scope: change.scope },
          }),
        );
      } else if (change.what === "app") {
        await data(
          api.POST("/api/assistants/apps/{grant_id}/access", {
            params: { path: { grant_id: change.id } },
            body: { scope: change.scope },
          }),
        );
      } else if (change.what === "revoke") {
        await data(api.POST("/api/assistants/tokens/{token_id}/revoke", { params: { path: { token_id: change.id } } }));
      } else {
        await data(
          api.POST("/api/assistants/apps/{grant_id}/disconnect", { params: { path: { grant_id: change.id } } }),
        );
      }
    },
    onSuccess: refresh,
  });
}
