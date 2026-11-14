// When a screen's data cannot be loaded: what went wrong, in the server's words where it gave them, and a way to try
// again (never an empty screen, and never "nothing here" when there may well be something).
import { messageOf } from "../api/messages";
import styles from "./LoadError.module.css";

export function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className={styles.box}>
      <p className={styles.error} role="alert">
        {messageOf(error)}
      </p>
      <button type="button" className={styles.retry} onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}
