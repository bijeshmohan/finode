// The segmented switcher (.chips.seg): one choice of a few, as a radio group the arrow keys move through.
import type { KeyboardEvent } from "react";

import styles from "./Chips.module.css";

interface ChipsProps<T extends string> {
  label: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}

export function Chips<T extends string>({ label, options, value, onChange }: ChipsProps<T>) {
  function move(event: KeyboardEvent, step: number) {
    event.preventDefault();
    const at = options.findIndex((o) => o.value === value);
    const next = options[(at + step + options.length) % options.length];
    if (next) onChange(next.value);
  }

  return (
    <div role="radiogroup" aria-label={label} className={styles.seg}>
      {options.map((option) => {
        const chosen = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={chosen}
            tabIndex={chosen ? 0 : -1}
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
