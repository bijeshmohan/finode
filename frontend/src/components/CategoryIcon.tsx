// A category's icon, drawn from category-icons.json (copied from Lucide; the server's list of names is
// backend/finode/category_icons.py, held equal by a test). Which icon a row leads with is the server's to say.
import set from "./category-icons.json";
import styles from "./CategoryIcon.module.css";

const paths: Record<string, string> = set.paths;

/** Each account type's icon, for the one screen that shows a type without a view naming it (Settings' order of
 * types); the server's copy is services/account_types.TYPE_ICONS, held equal by a test. */
export const accountTypeIcons: Record<string, string> = set.types;

/** The groups the icon picker shows, in order. */
export const categoryIconGroups: { name: string; icons: string[] }[] = set.groups;

/** An icon's name in words, for a screen reader: "shopping-cart" → "shopping cart". */
export function iconLabel(name: string): string {
  return name.replace(/-/g, " ");
}

/** Decorative: the category's name is always beside it. A name this build does not know draws the generic tag. */
export function CategoryIcon({ name, size = 20 }: { name: string; size?: 16 | 20 }) {
  const known = name in paths;
  return (
    <svg
      className={styles.icon}
      data-icon={known ? name : "tag"}
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      // Our own fixed markup from category-icons.json, never anything a person typed.
      dangerouslySetInnerHTML={{ __html: (known ? paths[name] : paths.tag) ?? "" }}
    />
  );
}
