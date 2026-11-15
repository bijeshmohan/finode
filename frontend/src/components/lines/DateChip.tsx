// A day as a chip that names it ("Today, 14 Nov"), with the native date picker laid over it: the Add screen's date, and
// the recurring form's Starts and Ends (`prefix`; with no day yet it reads `emptyLabel`).
import { useToday } from "../../app/session";
import { dateChip } from "../../lib/dates";
import { Icon } from "../Icon";
import styles from "./DateChip.module.css";

interface ChipProps {
  value: string | null;
  onChange: (day: string) => void;
  /** What the chip is called to a screen reader. */
  label?: string;
  /** A word before the day ("Starts"). */
  prefix?: string;
  /** What the chip reads with no day ("never"); without it a day is always set. */
  emptyLabel?: string;
}

export function DateChip({ value, onChange, label = "Date", prefix, emptyLabel }: ChipProps) {
  const today = useToday();
  return (
    <label className={styles.chip}>
      <Icon name="calendar" />
      {prefix && <span className={styles.prefix}>{prefix}</span>}
      <span className={value ? undefined : styles.empty}>{value ? dateChip(value, today) : emptyLabel}</span>
      <input
        type="date"
        aria-label={label}
        value={value ?? ""}
        required={emptyLabel === undefined}
        onChange={(event) => {
          if (event.target.value) onChange(event.target.value);
        }}
      />
    </label>
  );
}
