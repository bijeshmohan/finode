// The shared list row (partials/transaction_list.html's `.tx`): a name, a quiet second line, a figure at the right.
// Green and "+" only for money in; red only for a real negative; everything else is plain ink.
import type { ReactNode } from "react";
import { Link } from "react-router";

import styles from "./Row.module.css";

export type FigureTone = "in" | "out" | "plain";

interface RowProps {
  title: ReactNode;
  detail?: ReactNode;
  figure?: ReactNode;
  figureTone?: FigureTone;
  to?: string;
  onClick?: () => void;
}

export function Row({ title, detail, figure, figureTone = "plain", to, onClick }: RowProps) {
  const toneClass = figureTone === "plain" ? "" : styles[figureTone];
  const content = (
    <>
      <span className={styles.main}>
        <span className={styles.title}>{title}</span>
        {detail !== undefined && <span className={styles.sub}>{detail}</span>}
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
