// An amount: a decimal keypad, only what makes an amount can be typed, and on leaving it is written out whole and
// grouped (12,34,567.00 for rupees). The value is always a string; the server checks it again.
import { type Grouping, cleanAmount, groupAmount, tidyAmount } from "../lib/amount";
import styles from "./AmountField.module.css";

interface AmountFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  places: number;
  grouping: Grouping;
}

export function AmountField({ id, label, value, onChange, places, grouping }: AmountFieldProps) {
  return (
    <div className={styles.field}>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className={styles.input}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        placeholder={places ? `0.${"0".repeat(places)}` : "0"}
        value={value}
        onChange={(event) => {
          onChange(cleanAmount(event.target.value, places));
        }}
        onBlur={() => {
          const tidy = groupAmount(tidyAmount(value, places), grouping);
          if (tidy !== value) onChange(tidy);
        }}
      />
    </div>
  );
}
