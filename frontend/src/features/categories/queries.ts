// The Categories area's server data: the Categories page and a category's page for a month, where the category form
// starts, and what the page and the form change. Every change refreshes all views.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../transactions/queries";

export type CategoriesView = components["schemas"]["CategoriesView"];
export type CategoryView = components["schemas"]["CategoryView"];
export type CategoryFormView = components["schemas"]["CategoryFormView"];
export type CategoryUpdate = components["schemas"]["CategoryUpdate"];

export function useCategories(month: string | null, tab: string) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "categories", month ?? "", tab],
    queryFn: () => data(api.GET("/api/views/categories", { params: { query: { ...(month ? { month } : {}), tab } } })),
  });
}

export function useCategory(id: string, month: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "category", id, month ?? ""],
    queryFn: () =>
      data(
        api.GET("/api/views/categories/{category_id}", {
          params: { path: { category_id: id }, query: month ? { month } : {} },
        }),
      ),
  });
}

export function useCategoryForm(query: { category_id?: string; parent?: string; root?: string }) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "category-form", query],
    queryFn: () => data(api.GET("/api/views/category-form", { params: { query } })),
    staleTime: 0,
  });
}

/** Change, delete or restore a category (adding one is the Add screen's useAddCategory); every view is refreshed. */
export function useCategoryChange() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (
      change: { action: "delete" | "reopen"; id: string } | { action: "update"; id: string; body: CategoryUpdate },
    ): Promise<unknown> => {
      const path = { params: { path: { category_id: change.id } } };
      if (change.action === "update")
        return data(api.PATCH("/api/categories/{category_id}", { ...path, body: change.body }));
      if (change.action === "delete") return data(api.POST("/api/categories/{category_id}/delete", path));
      return data(api.POST("/api/categories/{category_id}/reopen", path));
    },
    onSuccess: async (_answer, change) => {
      if (change.action === "delete") {
        // An unused category is gone for good: its own views are dropped, not asked for again ("not found").
        queryClient.removeQueries({ queryKey: [...VIEWS, "category", change.id] });
        queryClient.removeQueries({ queryKey: [...VIEWS, "category-form"] });
      }
      await queryClient.invalidateQueries({ queryKey: VIEWS });
    },
  });
}
