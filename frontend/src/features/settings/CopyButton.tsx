// Copies a text (the assistants' address, a new token): the clipboard where the browser lets the page write to it,
// else the text is selected for the person to copy. It says "Copied" for a moment.
import { useState } from "react";

import styles from "./CopyButton.module.css";

export function CopyButton({ text, label, target }: { text: string; label: string; target?: string }) {
  const [copied, setCopied] = useState(false);
  const select = () => {
    const shown = target ? document.getElementById(target) : null;
    const range = shown ? document.createRange() : null;
    if (shown && range) {
      range.selectNodeContents(shown);
      window.getSelection()?.removeAllRanges();
      window.getSelection()?.addRange(range);
    }
  };
  return (
    <button
      type="button"
      className={styles.copy}
      onClick={() => {
        const done = () => {
          setCopied(true);
          setTimeout(() => {
            setCopied(false);
          }, 1500);
        };
        // Some browsers have no clipboard for a page at all; others refuse the write: either way the text is selected.
        if ("clipboard" in navigator) navigator.clipboard.writeText(text).then(done, select);
        else select();
      }}
    >
      {copied ? "Copied" : label}
    </button>
  );
}
