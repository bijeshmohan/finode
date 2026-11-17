// One short message at a time ("Saved"), gone after three seconds, read out by screen readers. A screen outside the
// layout (a password reset) hands one over in the navigation: `navigate("/", { state: { toast: "…" } })`.
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";

import styles from "./Layout.module.css";

const TOAST_LIFE_MS = 3000;

const ToastContext = createContext<(message: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<{ text: string; id: string } | null>(null);
  const show = useCallback((text: string) => {
    setMessage({ text, id: String(Date.now()) });
  }, []);

  // A toast handed over in the navigation is taken when the address changes, while rendering (React's way to adjust
  // state to a new input, without an extra render from an effect).
  const location = useLocation();
  const navigate = useNavigate();
  const handedOver = (location.state as { toast?: unknown } | null)?.toast;
  const [seen, setSeen] = useState<string | null>(null);
  if (location.key !== seen) {
    setSeen(location.key);
    if (typeof handedOver === "string") setMessage({ text: handedOver, id: location.key });
  }
  useEffect(() => {
    // Shown once: going back to this entry must not show it again.
    if (typeof handedOver === "string")
      void navigate(location.pathname + location.search, { replace: true, state: null });
  }, [handedOver, navigate, location.pathname, location.search]);

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
