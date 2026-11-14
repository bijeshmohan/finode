// Where to go after signing in: only an address inside the app (never another site: no open redirect) and never back
// to one of the sign-in screens. The address is read as the browser will read it (a tab or a newline inside it is
// dropped by the URL parser, which could otherwise turn "/\t/evil.example" into another site).
const SAME_SITE = "https://finode.invalid";
const SIGN_IN_SCREENS = ["/sign-in", "/login", "/sign-up", "/signup", "/forgot", "/reset"];

export function safeNext(next: string | null): string {
  // Control characters are what this looks for: the URL parser drops them silently.
  // eslint-disable-next-line no-control-regex
  if (!next?.startsWith("/") || /[\u0000-\u001F\u007F\\]/.test(next)) return "/";
  let url: URL;
  try {
    url = new URL(next, SAME_SITE);
  } catch {
    return "/";
  }
  if (url.origin !== SAME_SITE) return "/";
  const path = url.pathname.toLowerCase();
  if (SIGN_IN_SCREENS.some((screen) => path === screen || path.startsWith(`${screen}/`))) return "/";
  return url.pathname + url.search + url.hash;
}
