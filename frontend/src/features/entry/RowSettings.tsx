// The settings of a row, opened by the glyph at its right (#row-settings in txn_rows.html): its amount and, on an
// account, the day it posts the line; Done keeps them, Remove takes the row away when the side has several.
import { useState } from "react";

import { useGrouping, usePlaces } from "../../app/currency";
import { AmountField } from "../../components/AmountField";
import { Sheet } from "../../components/Sheet";
import styles from "./RowSettings.module.css";

export interface RowSettingsProps {
  title: string;
  amount: string;
  /** The day it posts, or null when no date is asked (a category or a person). */
  date: string | null;
  /** The entry's own date: a line cannot post before it. */
  entryDate: string;
  canRemove: boolean;
  onDone: (amount: string, date: string | null) => void;
  onRemove: () => void;
  onClose: () => void;
}

export function RowSettings({
  title,
  amount,
  date,
  entryDate,
  canRemove,
  onDone,
  onRemove,
  onClose,
}: RowSettingsProps) {
  const grouping = useGrouping();
  const places = usePlaces();
  const [typed, setTyped] = useState(amount);
  const [day, setDay] = useState(date);
  const done = () => {
    onDone(typed, day);
    onClose();
  };

  return (
    <Sheet open onClose={onClose} title={title}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          done();
        }}
      >
        <div className={day === null ? `${styles.fields} ${styles.one}` : styles.fields}>
          <div className={styles.field}>
            <AmountField
              id="row-amount"
              label="Amount"
              value={typed}
              onChange={setTyped}
              places={places}
              grouping={grouping}
            />
          </div>
          {day !== null && (
            <label className={styles.field}>
              Date
              <input
                type="date"
                min={entryDate}
                value={day}
                onChange={(event) => {
                  setDay(event.target.value);
                }}
              />
            </label>
          )}
        </div>
        <button type="submit" className={styles.done}>
          Done
        </button>
      </form>
      {canRemove && (
        <button
          type="button"
          className={styles.remove}
          onClick={() => {
            onRemove();
            onClose();
          }}
        >
          Remove
        </button>
      )}
    </Sheet>
  );
}
