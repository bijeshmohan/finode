// Choosing an account, a category or a person: our own sheet (app.js "Choosing an account or a category"), the same on
// iOS and Android. The groups are headed by their type; a search lists the matches with their group under each name;
// each shows its balance; the chosen one is bold and the other side's choice is greyed.
import { useState } from "react";

import { useGrouping } from "../../app/currency";
import { Sheet } from "../../components/Sheet";
import { formatMoney } from "../../lib/money";
import styles from "./Picker.module.css";
import type { PickGroup } from "./queries";

interface PickerProps {
  open: boolean;
  title: string;
  groups: PickGroup[];
  value: string | null;
  onChange: (id: string | null) => void;
  onClose: () => void;
  /** The choice on the other side of the entry: not offered again here. */
  otherSide?: string | null;
  /** When the row may name nothing, the label of that first choice ("No category"). */
  clearable?: string;
}

export function Picker({ open, title, groups, value, onChange, onClose, otherSide = null, clearable }: PickerProps) {
  const grouping = useGrouping();
  const [search, setSearch] = useState("");
  const wanted = search.trim().toLowerCase();
  const shown = wanted
    ? groups
        .map((g) => ({ ...g, options: g.options.filter((o) => o.label.toLowerCase().includes(wanted)) }))
        .filter((g) => g.options.length > 0)
    : groups;
  const choose = (id: string | null) => {
    setSearch("");
    onChange(id);
    onClose();
  };

  return (
    <Sheet open={open} onClose={onClose} title={title}>
      <input
        type="search"
        className={styles.search}
        placeholder="Search"
        aria-label="Search"
        autoComplete="off"
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
        }}
      />
      <div className={styles.list}>
        {clearable !== undefined && !wanted && (
          <button
            type="button"
            className={styles.option}
            aria-pressed={value === null}
            onClick={() => {
              choose(null);
            }}
          >
            <span className={styles.name}>{clearable}</span>
          </button>
        )}
        {shown.map((group) => (
          <section key={group.title}>
            {!wanted && <h3 className={styles.groupTitle}>{group.title}</h3>}
            {group.options.map((option) => (
              <button
                key={option.id}
                type="button"
                className={styles.option}
                aria-pressed={option.id === value}
                disabled={option.id === otherSide}
                // A tap keeps the search field's focus, so the sheet (and the keyboard) do not jump.
                onMouseDown={(event) => {
                  event.preventDefault();
                }}
                onClick={() => {
                  choose(option.id);
                }}
              >
                <span className={styles.name}>
                  {option.label}
                  {wanted && <small className={styles.under}>{group.title}</small>}
                </span>
                {option.balance !== null && (
                  <span className={styles.balance}>{formatMoney(option.balance, grouping)}</span>
                )}
              </button>
            ))}
          </section>
        ))}
      </div>
    </Sheet>
  );
}
