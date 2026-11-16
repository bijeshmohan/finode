// A new version of the app, once the service worker has it: put in when the page is next left (the person switched
// away, locked the phone), never while it is on screen, where reloading would lose an entry being typed.

/** Calls `apply` once, as soon as the page is hidden (at once if it already is). */
export function updateWhenHidden(apply: () => void): void {
  if (document.visibilityState === "hidden") {
    apply();
    return;
  }
  const onChange = () => {
    if (document.visibilityState !== "hidden") return;
    document.removeEventListener("visibilitychange", onChange);
    apply();
  };
  document.addEventListener("visibilitychange", onChange);
}
