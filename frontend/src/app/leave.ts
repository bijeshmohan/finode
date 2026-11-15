// Leaving the app for another site (an assistant's address after consent): a whole new page load, not a route.
export function leaveTo(url: string): void {
  window.location.assign(url);
}
