// Your data's server data: what the page offers, the previews and confirms of an import or a restore (the file as
// multipart), and erasing the books or the whole account. After a change everything held about the books refreshes, in
// the hooks themselves, so it happens even when the page is left before the answer comes.
import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, data } from "../../api/client";
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

/** What is not about the books, so survives their changing wholesale: who is signed in, the sign-in options, the
 * currencies and an app's consent. */
const KEPT = new Set(["session", "auth-options", "currencies", "consent"]);

/** After the books changed wholesale (an import, a restore, an erase): everything else held is asked for again, the
 * views, the profile, the tags and the payees offered. */
function refreshEverything(queryClient: QueryClient) {
  return queryClient.invalidateQueries({ predicate: (query) => !KEPT.has(String(query.queryKey[0])) });
}

/** Import and restore refresh once something was written: a confirm whose answer has no errors. */
function afterWriting(queryClient: QueryClient) {
  return (answer: { errors?: string[] }, { dryRun }: { dryRun: boolean }) =>
    dryRun || (answer.errors ?? []).length > 0 ? undefined : refreshEverything(queryClient);
}

export function useImport() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) =>
      data(
        api.POST("/api/import", {
          params: { query: dryRun ? { dry_run: true } : {} },
          body: { file: file.name },
          bodySerializer: asForm(file),
        }),
      ),
    onSuccess: afterWriting(queryClient),
  });
}

export function useRestore() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) =>
      data(
        api.POST("/api/restore", {
          params: { query: dryRun ? { dry_run: true } : {} },
          body: { file: file.name },
          bodySerializer: asForm(file),
        }),
      ),
    onSuccess: afterWriting(queryClient),
  });
}

export function useErase() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (confirm: string) => data(api.POST("/api/erase", { body: { confirm } })),
    onSuccess: () => refreshEverything(queryClient),
  });
}

/** Deleting the account; a 503 means the books were erased but the login stayed, so what is held is refreshed. */
export function useDeleteAccount() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (confirm: string) => data(api.POST("/api/delete-account", { body: { confirm } })),
    onError: (error) =>
      error instanceof ApiError && error.status === 503 ? refreshEverything(queryClient) : undefined,
  });
}
