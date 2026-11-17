// A banner while the device has no connection (finode works online only: nothing is saved for later).
import { useSyncExternalStore } from "react";

import styles from "./Layout.module.css";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

export function Offline() {
  const online = useSyncExternalStore(subscribe, () => navigator.onLine);
  if (online) return null;
  return (
    <div className={styles.netBanner} role="status">
      You&apos;re offline. finode needs a connection to show and save your books.
    </div>
  );
}
