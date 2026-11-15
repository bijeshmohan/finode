// The app's light or dark look, chosen on Settings for this browser only (the web pages kept it in a cookie the
// server read; the app is static files, so it keeps it here). index.html reads the same key before the first paint.
export type Theme = "auto" | "light" | "dark";

const KEY = "finode_theme";

export function readTheme(): Theme {
  try {
    const kept = localStorage.getItem(KEY);
    return kept === "light" || kept === "dark" ? kept : "auto";
  } catch {
    return "auto";
  }
}

/** Keep the choice and put it on the page at once; "auto" follows the device again. */
export function chooseTheme(choice: Theme): void {
  try {
    if (choice === "auto") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    // Storage refused (a private window): the choice still holds until the page is closed.
  }
  if (choice === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", choice);
}
