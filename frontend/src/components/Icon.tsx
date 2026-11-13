// The web pages' stroke icons (partials/icons.html), drawn from icons.json; tests/test_icon_parity.py keeps the two equal.
import icons from "./icons.json";

export type IconName = keyof typeof icons;

/** Decorative unless given a label, in which case it is an image with that name. */
export function Icon({ name, label }: { name: IconName; label?: string }) {
  const a11y = label ? { role: "img", "aria-label": label } : { "aria-hidden": true };
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...a11y}
      // Our own fixed markup from icons.json, never anything a person typed.
      dangerouslySetInnerHTML={{ __html: icons[name] }}
    />
  );
}
