// The browser tab's title, which history and the app switcher show too: the screen's name from its route
// (`handle: { title }` in router.tsx), or the name a screen gives itself once it has loaded (an account's, a
// category's, a person's, a budget group's), then "finode". Home is plain "finode".
import { createContext, type ReactNode, useContext, useEffect, useState } from "react";
import { useMatches } from "react-router";

export interface RouteHandle {
  title?: string;
}

const SetName = createContext<(name: string | undefined) => void>(() => undefined);

export function TabTitle({ children }: { children: ReactNode }) {
  const matches = useMatches();
  const routeTitle = (matches.at(-1)?.handle as RouteHandle | undefined)?.title;
  const [name, setName] = useState<string>();
  const shown = name ?? routeTitle;
  const title = shown ? `${shown} · finode` : "finode";
  useEffect(() => {
    document.title = title;
  }, [title]);
  return <SetName.Provider value={setName}>{children}</SetName.Provider>;
}

/** Names the tab after what this screen shows; until `name` is known the route's title stands. */
export function useTabTitle(name: string | undefined) {
  const setName = useContext(SetName);
  useEffect(() => {
    setName(name);
    return () => {
      setName(undefined);
    };
  }, [setName, name]);
}
