// The entry's day as a chip that names it ("Today, 14 Nov"), with the native date picker laid over it.
import { useToday } from "../../app/session";
import { Icon } from "../../components/Icon";
import { dateChip } from "../../lib/dates";
import styles from "./EntryScreen.module.css";

export function DateChip({ value, onChange }: { value: string; onChange: (day: string) => void }) {
  const today = useToday();
  return (
    <label className={styles.dateChip}>
      <Icon name="calendar" />
      <span>{dateChip(value, today)}</span>
      <input
        type="date"
        aria-label="Date"
        value={value}
        required
        onChange={(event) => {
          if (event.target.value) onChange(event.target.value);
        }}
      />
    </label>
  );
}
