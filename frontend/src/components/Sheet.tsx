// A bottom sheet: a modal dialog that slides up on phones and rises gently on wide screens. It stays mounted and is opened and closed with showModal() and close(), so the browser gives
// focus back to whatever opened it and the closing slide can play. Escape and a tap on the dimmed area close it.
// With `panelOnWide`, a wide screen with a mouse shows it as a panel beside the page instead (not modal: the list
// stays usable), with a close button (dialog.side-panel).
import { type ReactNode, useEffect, useId, useRef, useState } from "react";

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

const FIELDS = "input, select, textarea";

/** How much of the screen the soft keyboard takes (--kb) and how tall the visible part is (--vvh), so a bottom sheet
 * sits above the keyboard . With no field in a sheet focused there is no
 * keyboard, whatever the viewport says: iOS's keyboard-down tick sends no resize. Installed once for the whole app. */
let placing = false;
function placeAboveTheKeyboard(): void {
  if (placing || typeof window === "undefined") return;
  placing = true;
  const vv = window.visualViewport;
  const ios = /iP(hone|ad|od)/.test(navigator.userAgent);
  const place = () => {
    if (!vv) return;
    const field = document.activeElement;
    const typing = field instanceof HTMLElement && field.matches(FIELDS) && field.closest("dialog") !== null;
    const root = document.documentElement.style;
    root.setProperty(
      "--kb",
      `${String(typing ? Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)) : 0)}px`,
    );
    root.setProperty("--vvh", `${String(Math.round(vv.height))}px`);
    root.setProperty("--kb-bar", typing && ios ? "0.75rem" : "0px");
  };
  if (vv) {
    vv.addEventListener("resize", place);
    vv.addEventListener("scroll", place);
  }
  const inSheet = (target: EventTarget | null) =>
    target instanceof HTMLElement && target.matches(FIELDS) && target.closest("dialog") !== null;
  document.addEventListener("focusin", (event) => {
    if (inSheet(event.target)) place();
  });
  document.addEventListener("focusout", (event) => {
    // The keyboard is going: lower the sheet once the tap that caused it is over (a press on Save must not see the sheet
    // move under the finger), and look again as the viewport settles (iOS may send no event).
    if (!inSheet(event.target)) return;
    for (const ms of [100, 350, 700]) setTimeout(place, ms);
  });
  place();
}

function wideWithMouse(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(WIDE_WITH_MOUSE).matches;
}

export function Sheet({ open, onClose, title, showTitle = true, panelOnWide = false, children }: SheetProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const panel = panelOnWide && wideWithMouse();
  // While a field in it is focused the sheet shows only what is needed, so it fits above the keyboard (`typing`).
  const [typing, setTyping] = useState(false);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // A press that began inside never closes the sheet, even when the sheet moves under the finger and the release lands
  // on the dimmed area; a tap on the dimmed area while typing only puts the keyboard away.
  const pressedInside = useRef(false);
  const wasTyping = useRef(false);

  useEffect(() => {
    placeAboveTheKeyboard();
  }, []);

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
      data-side-panel={panel ? "" : undefined}
      aria-labelledby={showTitle ? titleId : undefined}
      aria-label={showTitle ? undefined : title}
      // A sheet opened from inside this one (the icon picker in a form sheet) sends its own cancel and close, which React
      // passes on to this one: only this dialog's own close it.
      onCancel={(event) => {
        if (event.target !== event.currentTarget) return;
        event.preventDefault();
        onClose();
      }}
      // The browser can close a dialog by itself (a repeated Escape): the page is told, so React and the dialog agree.
      onClose={(event) => {
        if (event.target === event.currentTarget && open) onClose();
      }}
      data-typing={typing ? "" : undefined}
      onPointerDown={(event) => {
        const field = document.activeElement;
        pressedInside.current = event.target !== event.currentTarget;
        wasTyping.current =
          event.target === event.currentTarget &&
          field instanceof HTMLElement &&
          event.currentTarget.contains(field) &&
          field.matches(FIELDS);
      }}
      onFocus={(event) => {
        if (!(event.target instanceof HTMLElement) || !event.target.matches(FIELDS)) return;
        clearTimeout(typingTimer.current);
        setTyping(true);
      }}
      onBlur={(event) => {
        if (!(event.target instanceof HTMLElement) || !event.target.matches(FIELDS)) return;
        // Later than the tap on Save that caused it, so the sheet does not change shape under the finger.
        typingTimer.current = setTimeout(() => {
          setTyping(false);
        }, 300);
      }}
      onClick={(event) => {
        if (panel || event.target !== event.currentTarget) return;
        if (pressedInside.current) {
          pressedInside.current = false;
          return;
        }
        if (wasTyping.current) {
          wasTyping.current = false;
          const field = document.activeElement;
          if (field instanceof HTMLElement && event.currentTarget.contains(field)) field.blur();
          return;
        }
        onClose();
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
