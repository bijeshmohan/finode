// What an empty list says: what is missing, and the step that fills it.
import type { ReactNode } from "react";

import styles from "./EmptyState.module.css";

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={styles.empty}>
      <p className={styles.title}>{title}</p>
      {children}
      {action}
    </div>
  );
}
