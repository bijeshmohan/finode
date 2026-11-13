// Who is signed in, and today's date as finode counts it (FINODE_TIMEZONE), from /api/auth/session. Every screen inside
// the layout can rely on a session: signed out goes to sign-in, and a lost connection says so (never "sign in").
import { useQuery } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext } from "react";
import { Navigate, useLocation } from "react-router";

import { ApiError, data } from "../api/client";
import { useApi } from "../api/context";
import type { components } from "../api/schema";

export type Session = components["schemas"]["SessionRead"];

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const location = useLocation();
  const session = useQuery({ queryKey: ["session"], queryFn: () => data(api.GET("/api/auth/session")) });

  if (session.isPending) return null;
  if (session.error instanceof ApiError && session.error.status === 401) {
    const next = location.pathname + location.search;
    return <Navigate to={`/sign-in?next=${encodeURIComponent(next)}`} replace />;
  }
  // A failed refresh keeps the app on screen with the session it has (the offline banner says why); only a first load
  // that cannot reach finode replaces the screen.
  if (session.data === undefined) {
    return (
      <div className="unreachable" role="alert">
        <p>finode can&apos;t be reached. Check your connection.</p>
        <button type="button" onClick={() => void session.refetch()}>
          Try again
        </button>
      </div>
    );
  }
  return <SessionContext value={session.data}>{children}</SessionContext>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession is only for screens inside SessionProvider");
  return session;
}

/** Today (YYYY-MM-DD) where finode's people live: never the device's own clock. */
export function useToday(): string {
  return useSession().today;
}
