// Where to go after signing in: only an address inside the app, never another site (an open redirect) and never back
// to sign-in itself.
export function safeNext(next: string | null): string {
  if (!next?.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/";
  if (next === "/sign-in" || next.startsWith("/sign-in?") || next.startsWith("/sign-in/")) return "/";
  return next;
}
