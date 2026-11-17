// The Tags page's server data: the person's tags (most used first), and renaming (onto another tag: a merge) or
// deleting one. Every change refreshes all views, so the lists that show tags follow.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../../api/views";

export type Tag = components["schemas"]["TagRead"];

export function useTags() {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "tags"],
    queryFn: () => data(api.GET("/api/tags/")),
  });
}

function useRefresh() {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: VIEWS });
  };
}

/** Rename a tag; when the new name is another of the person's tags the two become one (Merge into… sends that). */
export function useRenameTag() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ name, to }: { name: string; to: string }) =>
      data(api.PATCH("/api/tags/{name}", { params: { path: { name } }, body: { name: to } })),
    onSuccess: refresh,
  });
}

export function useDeleteTag() {
  const api = useApi();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (name: string) => data(api.DELETE("/api/tags/{name}", { params: { path: { name } } })),
    onSuccess: refresh,
  });
}
