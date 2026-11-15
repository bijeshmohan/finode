// One row of Settings and the pages under it (.setting): a title with its value beside the chevron, opening what is
// under it; or a link to another page. Opened by the address too (/settings#currency).
import { type ReactNode, useState } from "react";
import { Link, useLocation } from "react-router";

import { Icon } from "../../components/Icon";
import styles from "./Settings.module.css";

interface RowProps {
  id: string;
  title: string;
  value?: string;
  danger?: boolean;
  children: ReactNode;
}

export function SettingRow({ id, title, value, danger = false, children }: RowProps) {
  const location = useLocation();
  // Open when the address names the row, until it is tapped (then it follows the taps).
  const [tapped, setTapped] = useState<boolean | null>(null);
  const open = tapped ?? location.hash === `#${id}`;
  return (
    <div id={id} className={styles.setting}>
      <button
        type="button"
        className={styles.head}
        aria-expanded={open}
        aria-controls={`${id}-body`}
        onClick={() => {
          setTapped(!open);
        }}
      >
        <span className={danger ? `${styles.title} ${styles.danger}` : styles.title}>{title}</span>
        {value !== undefined && <span className={styles.value}>{value}</span>}
        <Icon name="chevron-right" />
      </button>
      {open && (
        <div id={`${id}-body`} className={styles.body}>
          {children}
        </div>
      )}
    </div>
  );
}

export function SettingLink({ id, title, to }: { id: string; title: string; to: string }) {
  const external = /^https?:/.test(to);
  const content = (
    <>
      <span className={styles.title}>{title}</span>
      <Icon name="chevron-right" />
    </>
  );
  return (
    <div id={id} className={styles.setting}>
      {external ? (
        <a className={styles.head} href={to}>
          {content}
        </a>
      ) : (
        <Link className={styles.head} to={to}>
          {content}
        </Link>
      )}
    </div>
  );
}
