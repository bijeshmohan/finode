// One short message at a time ("Saved"), gone after three seconds, read out by screen readers.
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";

import styles from "./Layout.module.css";

const TOAST_LIFE_MS = 3000;

const ToastContext = createContext<(message: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<{ text: string; id: number } | null>(null);
  const show = useCallback((text: string) => {
    setMessage({ text, id: Date.now() });
  }, []);

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => {
      setMessage(null);
    }, TOAST_LIFE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [message]);

  return (
    <ToastContext value={show}>
      {children}
      <div role="status" className={styles.toastRegion}>
        {message && (
          <span key={message.id} className={styles.toast}>
            {message.text}
          </span>
        )}
      </div>
    </ToastContext>
  );
}

export function useToast(): (message: string) => void {
  return useContext(ToastContext);
}
