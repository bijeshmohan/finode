// A bottom sheet: a modal dialog that slides up on phones and rises gently on wide screens (dialog.sheet in
// app/static/style.css). It stays mounted and is opened and closed with showModal() and close(), so the browser gives
// focus back to whatever opened it and the closing slide can play. Escape and a tap on the dimmed area close it.
// With `panelOnWide`, a wide screen with a mouse shows it as a panel beside the page instead (not modal: the list
// stays usable), with a close button (dialog.side-panel).
import { type ReactNode, useEffect, useId, useRef } from "react";

import styles from "./Sheet.module.css";

const WIDE_WITH_MOUSE = "(min-width: 60rem) and (hover: hover)";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Show the title as the heading (sheets whose content draws its own heading pass false). */
  showTitle?: boolean;
  panelOnWide?: boolean;
  children: ReactNode;
}

function wideWithMouse(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(WIDE_WITH_MOUSE).matches;
}

export function Sheet({ open, onClose, title, showTitle = true, panelOnWide = false, children }: SheetProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const panel = panelOnWide && wideWithMouse();

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      if (panel) element.show();
      else element.showModal();
    }
    if (!open && element.open) element.close();
  }, [open, panel]);

  // A panel is not modal, so the dialog sends no cancel on Escape: listen for it.
  useEffect(() => {
    if (!open || !panel) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
    };
  }, [open, panel, onClose]);

  return (
    // A tap on the dialog itself (not its content) is a tap on the dimmed area around the sheet; Escape is the keyboard
    // way to close it, through the dialog's own cancel event.
    // eslint-disable-next-line jsx-a11y-x/click-events-have-key-events, jsx-a11y-x/no-noninteractive-element-interactions
    <dialog
      ref={dialog}
      className={`${styles.sheet} ${panel ? styles.panel : ""}`.trim()}
      aria-labelledby={showTitle ? titleId : undefined}
      aria-label={showTitle ? undefined : title}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      // The browser can close a dialog by itself (a repeated Escape): the page is told, so React and the dialog agree.
      onClose={() => {
        if (open) onClose();
      }}
      onClick={(event) => {
        if (!panel && event.target === event.currentTarget) onClose();
      }}
    >
      {panel && (
        <button type="button" className={styles.close} aria-label="Close" onClick={onClose}>
          ×
        </button>
      )}
      <div className={styles.body}>
        <span className={styles.grab} aria-hidden="true" />
        {showTitle && (
          <h2 id={titleId} className={styles.title}>
            {title}
          </h2>
        )}
        {children}
      </div>
    </dialog>
  );
}
