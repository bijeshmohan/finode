// Where the "+" of the bar starts a new entry. Most pages leave it at /transactions/new; an account's or a category's
// page starts it for that account or category and comes back there (base.html's `new_transaction_url`).
import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

const NEW_TRANSACTION = "/transactions/new";

const Here = createContext<[string, (url: string | null) => void]>([NEW_TRANSACTION, () => undefined]);

export function NewEntryProvider({ children }: { children: ReactNode }) {
  const [url, setUrl] = useState<string | null>(null);
  return <Here.Provider value={[url ?? NEW_TRANSACTION, setUrl]}>{children}</Here.Provider>;
}

/** Where the "+" goes now. */
export function useNewEntryUrl(): string {
  return useContext(Here)[0];
}

/** Point the "+" at `url` while this page is shown (null: the usual new entry). */
export function useNewEntryHere(url: string | null): void {
  const set = useContext(Here)[1];
  useEffect(() => {
    set(url);
    return () => {
      set(null);
    };
  }, [set, url]);
}
