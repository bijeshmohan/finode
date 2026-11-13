// The month selector: ‹ Nov 2026 ›, with the native month picker laid invisibly over the name (partials/month_pill.html).
import { Icon } from "./Icon";
import styles from "./MonthPill.module.css";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;

/** `YYYY-MM` moved by `step` months. */
export function shiftMonth(month: string, step: number): string {
  const [year = 0, number = 1] = month.split("-").map(Number);
  const index = year * 12 + (number - 1) + step;
  return `${String(Math.floor(index / 12)).padStart(4, "0")}-${String((index % 12) + 1).padStart(2, "0")}`;
}

interface MonthPillProps {
  month: string;
  onChange: (month: string) => void;
  max?: string;
}

export function MonthPill({ month, onChange, max = "2999-12" }: MonthPillProps) {
  const [year = "", number = "1"] = month.split("-");
  const next = shiftMonth(month, 1);
  return (
    <span className={styles.pill}>
      <button
        type="button"
        className={styles.arrow}
        aria-label="Previous month"
        onClick={() => {
          onChange(shiftMonth(month, -1));
        }}
      >
        <Icon name="back" />
      </button>
      <span className={styles.pick}>
        <span>
          {MONTHS[Number(number) - 1]} {year}
        </span>
        <input
          type="month"
          className={styles.input}
          value={month}
          min="1900-01"
          max={max}
          aria-label="Choose a month"
          onChange={(event) => {
            if (event.target.value) onChange(event.target.value);
          }}
        />
      </span>
      <button
        type="button"
        className={`${styles.arrow} ${styles.forward}`}
        aria-label="Next month"
        disabled={next > max}
        onClick={() => {
          onChange(next);
        }}
      >
        <Icon name="back" />
      </button>
    </span>
  );
}
