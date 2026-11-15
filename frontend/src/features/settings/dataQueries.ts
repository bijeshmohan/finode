// Your data's server data: what the page offers, the previews and confirms of an import or a restore (the file as
// multipart), and erasing the books or the whole account. After a change every view refreshes.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../../api/views";

export type ImportSummary = components["schemas"]["ImportSummary"];
export type RestoreSummary = components["schemas"]["RestoreSummary"];

export function useDataOptions() {
  const api = useApi();
  return useQuery({ queryKey: [...VIEWS, "data-options"], queryFn: () => data(api.GET("/api/data-options")) });
}

/** The file as the API takes it: one multipart field. */
function asForm(file: File) {
  return () => {
    const form = new FormData();
    form.append("file", file);
    return form;
  };
}

export function useImport() {
  const api = useApi();
  return useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) =>
      data(
        api.POST("/api/import", {
          params: { query: dryRun ? { dry_run: true } : {} },
          body: { file: file.name },
          bodySerializer: asForm(file),
        }),
      ),
  });
}

export function useRestore() {
  const api = useApi();
  return useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) =>
      data(
        api.POST("/api/restore", {
          params: { query: dryRun ? { dry_run: true } : {} },
          body: { file: file.name },
          bodySerializer: asForm(file),
        }),
      ),
  });
}

export function useErase() {
  const api = useApi();
  return useMutation({ mutationFn: (confirm: string) => data(api.POST("/api/erase", { body: { confirm } })) });
}

export function useDeleteAccount() {
  const api = useApi();
  return useMutation({ mutationFn: (confirm: string) => data(api.POST("/api/delete-account", { body: { confirm } })) });
}

/** After the books changed wholesale (an import, a restore, an erase): every view and the profile again. */
export function useEverythingChanged() {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: VIEWS }),
      queryClient.invalidateQueries({ queryKey: ["profile"] }),
    ]);
  };
}
