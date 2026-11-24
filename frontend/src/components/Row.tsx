// The shared list row: a name, a quiet second line, a figure at the right.
// Green and "+" only for money in; red only for a real negative; everything else is plain ink.
import type { ReactNode } from "react";
import { Link } from "react-router";

import { CategoryIcon } from "./CategoryIcon";
import styles from "./Row.module.css";

export type FigureTone = "in" | "out" | "plain";

interface RowProps {
  title: ReactNode;
  detail?: ReactNode;
  /** Quiet markers under the second line (Recurring, Added by an assistant). */
  extra?: ReactNode;
  figure?: ReactNode;
  figureTone?: FigureTone;
  to?: string;
  onClick?: () => void;
  /** The icon the row leads with (a category's, or the server's mark for the entry), quiet, before the name. */
  icon?: string | undefined;
}

export function Row({ title, detail, extra, figure, figureTone = "plain", to, onClick, icon }: RowProps) {
  const toneClass = figureTone === "plain" ? "" : styles[figureTone];
  const content = (
    <>
      {icon !== undefined && (
        <span className={styles.icon}>
          <CategoryIcon name={icon} />
        </span>
      )}
      <span className={styles.main}>
        <span className={styles.title}>{title}</span>
        {detail !== undefined && <span className={styles.sub}>{detail}</span>}
        {extra}
      </span>
      {figure !== undefined && (
        <span className={`${styles.figure} ${toneClass}`.trim()}>
          {figureTone === "in" ? "+" : ""}
          {figure}
        </span>
      )}
    </>
  );
  if (to !== undefined)
    return (
      <Link to={to} className={styles.row}>
        {content}
      </Link>
    );
  if (onClick)
    return (
      <button type="button" className={styles.row} onClick={onClick}>
        {content}
      </button>
    );
  return <div className={styles.row}>{content}</div>;
}
