// A bottom sheet: a modal dialog that slides up on phones and rises gently on wide screens (dialog.sheet in
// app/static/style.css). Escape and a tap on the dimmed area close it; the browser returns focus to the opener.
import { type ReactNode, useEffect, useId, useRef } from "react";

import styles from "./Sheet.module.css";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

export function Sheet({ open, onClose, title, children }: SheetProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const element = dialog.current;
    if (open && element && !element.open) element.showModal();
  }, [open]);

  if (!open) return null;
  return (
    // A tap on the dialog itself (not its content) is a tap on the dimmed area around the sheet; Escape is the keyboard
    // way to close it, through the dialog's own cancel event.
    // eslint-disable-next-line jsx-a11y-x/click-events-have-key-events, jsx-a11y-x/no-noninteractive-element-interactions
    <dialog
      ref={dialog}
      className={styles.sheet}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={styles.body}>
        <span className={styles.grab} aria-hidden="true" />
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        {children}
      </div>
    </dialog>
  );
}
