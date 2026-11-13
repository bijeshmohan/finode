// The parts the sign-in forms are made of, in the look of the web pages' forms (label, .error, .login-notice, .switch).
import type { ReactNode } from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

import styles from "./fields.module.css";

interface TextFieldProps {
  label: string;
  registration: UseFormRegisterReturn;
  type?: "email" | "password" | "text";
  autoComplete: string;
  /** The field the screen starts in, as the web pages do. */
  startHere?: boolean;
  error?: string | undefined;
}

export function TextField({
  label,
  registration,
  type = "text",
  autoComplete,
  startHere = false,
  error,
}: TextFieldProps) {
  return (
    <label className={styles.label}>
      {label}
      <input
        className={styles.input}
        type={type}
        autoComplete={autoComplete}
        // The first field of a sign-in screen, as on the web pages.
        // eslint-disable-next-line jsx-a11y-x/no-autofocus
        autoFocus={startHere}
        aria-invalid={error ? true : undefined}
        {...registration}
      />
      {error && (
        <span className={styles.fieldError} role="alert">
          {error}
        </span>
      )}
    </label>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className={styles.error} role="alert">
      {message}
    </p>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <p className={styles.notice} role="status">
      {children}
    </p>
  );
}

export function SubmitButton({ pending, children }: { pending: boolean; children: ReactNode }) {
  return (
    <button type="submit" className={styles.button} disabled={pending} aria-busy={pending}>
      {children}
    </button>
  );
}

export function SwitchLine({ children }: { children: ReactNode }) {
  return <p className={styles.switchLine}>{children}</p>;
}

export function Stack({ children, onSubmit }: { children: ReactNode; onSubmit: () => void }) {
  return (
    <form
      className={styles.stack}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      {children}
    </form>
  );
}
