// The segmented switcher (.chips.seg): one choice of a few, as a radio group the arrow keys move through.
import { type KeyboardEvent, useRef } from "react";

import styles from "./Chips.module.css";

interface ChipsProps<T extends string> {
  label: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}

export function Chips<T extends string>({ label, options, value, onChange }: ChipsProps<T>) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const chosen = options.findIndex((o) => o.value === value);
  // The one chip Tab lands on: the chosen one, or the first when nothing matches.
  const focusable = chosen === -1 ? 0 : chosen;

  // The radio-group pattern: the arrow keys move the choice and the focus together.
  function move(event: KeyboardEvent, step: number) {
    event.preventDefault();
    const at = (focusable + step + options.length) % options.length;
    const next = options[at];
    if (!next) return;
    onChange(next.value);
    buttons.current[at]?.focus();
  }

  return (
    <div role="radiogroup" aria-label={label} className={styles.seg}>
      {options.map((option, index) => {
        return (
          <button
            key={option.value}
            ref={(element) => {
              buttons.current[index] = element;
            }}
            type="button"
            role="radio"
            aria-checked={index === chosen}
            tabIndex={index === focusable ? 0 : -1}
            className={styles.chip}
            onClick={() => {
              onChange(option.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "ArrowDown") move(event, 1);
              if (event.key === "ArrowLeft" || event.key === "ArrowUp") move(event, -1);
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
