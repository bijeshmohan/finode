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

/** How many decimals the person's currency keeps (2 for rupees, 0 for yen). */
export function usePlaces(): number {
  const api = useApi();
  const code = useCurrency();
  const currencies = useQuery({
    queryKey: ["currencies"],
    queryFn: () => data(api.GET("/api/profile/currencies")),
    staleTime: Infinity,
  });
  return currencies.data?.find((c) => c.code === code)?.decimals ?? 2;
}

/** The sign written beside an amount: ₹ for rupees, else the code. */
export function useSymbol(): string {
  const code = useCurrency();
  return code === "INR" ? "₹" : (code ?? "");
}
