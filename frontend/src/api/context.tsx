// Components take the API client from context, never by importing `api`, so a test can hand them a stubbed one.
import { createContext, type ReactNode, useContext } from "react";

import { api, type ApiClient } from "./client";

const ApiContext = createContext<ApiClient>(api);

export function ApiProvider({ client, children }: { client: ApiClient; children: ReactNode }) {
  return <ApiContext value={client}>{children}</ApiContext>;
}

export function useApi(): ApiClient {
  return useContext(ApiContext);
}
