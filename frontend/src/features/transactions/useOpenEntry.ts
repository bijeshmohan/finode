// Which entry's details are open, kept in the address (?open=<id>) so the back button closes the sheet.
import { useCallback } from "react";
import { useSearchParams } from "react-router";

export function useOpenEntry(): [string | null, (id: string) => void, () => void] {
  const [params, setParams] = useSearchParams();
  const open = params.get("open");
  const show = useCallback(
    (id: string) => {
      setParams((p) => {
        const next = new URLSearchParams(p);
        next.set("open", id);
        return next;
      });
    },
    [setParams],
  );
  const close = useCallback(() => {
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        next.delete("open");
        return next;
      },
      { replace: true },
    );
  }, [setParams]);
  return [open, show, close];
}
