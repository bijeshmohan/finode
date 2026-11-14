// Home's server data: one call for the screen (/api/views/home), then the rest of the month a few at a time.
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../transactions/queries";

export type HomeView = components["schemas"]["HomeView"];

/** How many more entries each "Show more" brings on Home. */
export const HOME_MORE = 10;

export function useHome(month: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "home", month ?? ""],
    queryFn: () => data(api.GET("/api/views/home", { params: { query: month ? { month } : {} } })),
  });
}

/** The month's entries after the first ones Home shows; nothing is asked until `wanted`. */
export function useHomeMore(month: string, start: number, wanted: boolean) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: [...VIEWS, "home-more", month, start],
    queryFn: ({ pageParam }) =>
      data(api.GET("/api/views/transactions", { params: { query: { month, offset: pageParam, limit: HOME_MORE } } })),
    initialPageParam: start,
    getNextPageParam: (last, pages) => {
      const shown = start + pages.reduce((n, page) => n + page.rows.length, 0);
      return shown < last.total && last.rows.length > 0 ? shown : undefined;
    },
    enabled: wanted,
  });
}
