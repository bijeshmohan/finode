// The "…" menu of an account's or a category's page (details.menu) and the "i" beside its name (details.note-info).
// They open under the title in the same place, so the page keeps which one is open and opening one closes the other.
import type { ReactNode } from "react";

import { Icon } from "./Icon";
import styles from "./Menu.module.css";

export type HeroOpen = "menu" | "info" | null;

interface HeldProps {
  open: boolean;
  onToggle: (open: boolean) => void;
}

export function Menu({ open, onToggle, children }: HeldProps & { children: ReactNode }) {
  return (
    <details
      className={styles.holder}
      open={open}
      onToggle={(event) => {
        if (event.currentTarget.open !== open) onToggle(event.currentTarget.open);
      }}
    >
      <summary className={styles.circ} title="More" aria-label="More actions">
        <Icon name="more" />
      </summary>
      <div className={styles.panel}>{children}</div>
    </details>
  );
}

export function InfoNote({ open, onToggle, label, text }: HeldProps & { label: string; text: string }) {
  return (
    <details
      className={styles.holder}
      open={open}
      onToggle={(event) => {
        if (event.currentTarget.open !== open) onToggle(event.currentTarget.open);
      }}
    >
      <summary className={styles.info} title={label} aria-label={label}>
        <Icon name="info" />
      </summary>
      <div className={`${styles.panel} ${styles.infoPanel}`}>
        <p className={styles.note}>{text}</p>
      </div>
    </details>
  );
}

/** A quiet line inside the menu (what closing or deleting does). */
export function MenuNote({ children }: { children: ReactNode }) {
  return <p className={styles.note}>{children}</p>;
}

export const menuStyles = styles;
