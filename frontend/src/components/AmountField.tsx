// An amount: a decimal keypad, only what makes an amount can be typed, and on leaving it is written out whole and
// grouped (12,34,567.00 for rupees). With `groupAsTyped` the commas go in as you type (the Add screen's amount). When
// cleaning or grouping changes the text, the cursor stays after the same digits. The value is always a string; the
// server checks it again.
import { useLayoutEffect, useRef } from "react";

import { type Grouping, cleanAmount, groupAmount, tidyAmount } from "../lib/amount";
import styles from "./AmountField.module.css";

interface AmountFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  places: number;
  grouping: Grouping;
  groupAsTyped?: boolean;
  /** The Add screen's big amount: no visible label, centred and large. */
  big?: boolean;
  autoFocus?: boolean;
}

const KEPT = /[\d.-]/;

/** How many characters that make the amount come before `caret` in `text`. */
function keptBefore(text: string, caret: number): number {
  let n = 0;
  for (const ch of text.slice(0, caret)) if (KEPT.test(ch)) n += 1;
  return n;
}

/** How many commas sit between the last character that makes the amount and `caret` (the cursor was after them). */
function commasBefore(text: string, caret: number): number {
  let n = 0;
  for (let i = caret - 1; i >= 0 && !KEPT.test(text.charAt(i)); i -= 1) if (text.charAt(i) === ",") n += 1;
  return n;
}

/** The position in `text` right after its `n`th character that makes the amount, then over up to `commas` commas. */
function caretAt(text: string, n: number, commas: number): number {
  let at = positionAfter(text, n);
  for (let skipped = 0; skipped < commas && text.charAt(at) === ","; skipped += 1) at += 1;
  return at;
}

/** The position in `text` right after its `n`th character that makes the amount. */
function positionAfter(text: string, n: number): number {
  if (n === 0) return 0;
  let seen = 0;
  for (let i = 0; i < text.length; i += 1) {
    if (KEPT.test(text.charAt(i))) seen += 1;
    if (seen === n) return i + 1;
  }
  return text.length;
}

export function AmountField({
  id,
  label,
  value,
  onChange,
  places,
  grouping,
  groupAsTyped = false,
  big = false,
  autoFocus = false,
}: AmountFieldProps) {
  const input = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);

  useLayoutEffect(() => {
    const field = input.current;
    if (field && caret.current !== null && document.activeElement === field) {
      field.setSelectionRange(caret.current, caret.current);
    }
    caret.current = null;
  }, [value]);

  return (
    <div className={`${styles.field} ${big ? styles.big : ""}`.trim()}>
      <label htmlFor={id} className={big ? "sr-only" : undefined}>
        {label}
      </label>
      <input
        ref={input}
        id={id}
        className={styles.input}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        // The Add screen's amount on a computer (the screen decides; never on a phone, where it would raise the keypad).
        // eslint-disable-next-line jsx-a11y-x/no-autofocus
        autoFocus={autoFocus}
        placeholder={places ? `0.${"0".repeat(places)}` : "0"}
        value={value}
        onChange={(event) => {
          const raw = event.target.value;
          const at = event.target.selectionStart ?? raw.length;
          const clean = cleanAmount(raw, places);
          const next = groupAsTyped ? groupAmount(clean, grouping) : clean;
          const position = caretAt(next, keptBefore(raw, at), commasBefore(raw, at));
          if (next === value) {
            // Nothing to re-render (a letter was dropped): React puts its own value back, then the cursor goes back.
            const field = event.target;
            queueMicrotask(() => {
              field.setSelectionRange(position, position);
            });
            return;
          }
          caret.current = position;
          onChange(next);
        }}
        onBlur={() => {
          const tidy = groupAmount(tidyAmount(value, places), grouping);
          if (tidy !== value) onChange(tidy);
        }}
      />
    </div>
  );
}
