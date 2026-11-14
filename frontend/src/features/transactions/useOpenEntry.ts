// Which entry's details are open, kept in the address (?open=<id>) so the back button closes the sheet. Opening adds one
// step to the history (one sheet opening another replaces it); closing goes back over that step, so no dead entry is
// left for the next Back. A page that arrived with ?open= in its address closes by dropping it.
import { useCallback } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

interface SheetState {
  sheet?: boolean;
}

export function useOpenEntry(): [string | null, (id: string) => void, () => void] {
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const open = params.get("open");
  const pushedHere = (location.state as SheetState | null)?.sheet === true;

  const show = useCallback(
    (id: string) => {
      const next = new URLSearchParams(location.search);
      next.set("open", id);
      // A sheet opened from a sheet replaces it, and keeps whether the first one added a step.
      const replacing = open !== null;
      void navigate(
        { pathname: location.pathname, search: `?${next.toString()}` },
        { state: { sheet: replacing ? pushedHere : true }, replace: replacing },
      );
    },
    [location.pathname, location.search, navigate, open, pushedHere],
  );

  const close = useCallback(() => {
    if (open === null) return; // closed already: a second close must not step back off the page
    if (pushedHere) {
      void navigate(-1);
      return;
    }
    const next = new URLSearchParams(location.search);
    next.delete("open");
    const search = next.toString();
    void navigate({ pathname: location.pathname, search: search ? `?${search}` : "" }, { replace: true });
  }, [open, pushedHere, location.pathname, location.search, navigate]);

  return [open, show, close];
}
