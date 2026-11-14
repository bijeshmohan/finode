// Home's server data: the glance and first steps (/api/views/home), and the month's entries as one list, a few first
// and more on "Show more", so a change to the books refreshes every page of it at once (no row twice, none lost).
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../transactions/queries";

export type HomeView = components["schemas"]["HomeView"];

/** Home starts with this many entries, and each "Show more" brings this many more (a day is never cut). */
export const HOME_FIRST = 8;
export const HOME_MORE = 10;

export function useHome(month: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "home", month ?? ""],
    queryFn: () => data(api.GET("/api/views/home", { params: { query: month ? { month } : {} } })),
  });
}

export function useHomeList(month: string | undefined) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: [...VIEWS, "home-list", month ?? ""],
    queryFn: ({ pageParam }) =>
      data(
        api.GET("/api/views/transactions", {
          params: {
            query: { ...(month ? { month } : {}), offset: pageParam, limit: pageParam === 0 ? HOME_FIRST : HOME_MORE },
          },
        }),
      ),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const shown = pages.reduce((n, page) => n + page.rows.length, 0);
      return shown < last.total && last.rows.length > 0 ? shown : undefined;
    },
  });
}
