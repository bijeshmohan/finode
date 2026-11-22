// The to-do bell's server data: what needs a decision now.
import { useQuery } from "@tanstack/react-query";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import type { components } from "../../api/schema";
import { VIEWS } from "../../api/views";

export type TodoView = components["schemas"]["TodoView"];

export function useTodo() {
  const api = useApi();
  return useQuery({
    queryKey: [...VIEWS, "todo"],
    queryFn: () => data(api.GET("/api/views/todo")),
  });
}
