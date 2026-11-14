// How the person's currency groups digits, from their profile (lakhs and crores for rupees).
import { useQuery } from "@tanstack/react-query";

import { data } from "../api/client";
import { useApi } from "../api/context";
import { type Grouping, groupingFor } from "../lib/amount";

export function useProfile() {
  const api = useApi();
  return useQuery({ queryKey: ["profile"], queryFn: () => data(api.GET("/api/profile/")), staleTime: Infinity });
}

export function useCurrency(): string | null {
  return useProfile().data?.default_currency ?? null;
}

export function useGrouping(): Grouping {
  return groupingFor(useCurrency());
}
