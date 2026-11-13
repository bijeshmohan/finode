// A bottom sheet: a modal dialog that slides up on phones and rises gently on wide screens (dialog.sheet in
// app/static/style.css). It stays mounted and is opened and closed with showModal() and close(), so the browser gives
// focus back to whatever opened it and the closing slide can play. Escape and a tap on the dimmed area close it.
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
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

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
      // The browser can close a dialog by itself (a repeated Escape): the page is told, so React and the dialog agree.
      onClose={() => {
        if (open) onClose();
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
