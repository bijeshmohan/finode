// The "i" beside a headline figure and the panel it opens: the sum behind the figure, with the person's own numbers
// (partials/calc_info.html). A negative line flips its sign, so every line is a positive number and the column adds up.
import { useId } from "react";

import { useCurrency, useGrouping } from "../../app/currency";
import { Icon } from "../../components/Icon";
import { formatMoney, withCurrency } from "../../lib/money";
import styles from "./Home.module.css";

export interface CalcLine {
  label: string;
  amount: string;
  sign: "" | "+" | "−";
}

export function CalcButton({ what, open, onToggle }: { what: string; open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className={`${styles.infoButton} ${open ? styles.infoOpen : ""}`.trim()}
      aria-label={`How ${what} is worked out`}
      aria-expanded={open}
      title="How this is worked out"
      onClick={onToggle}
    >
      <Icon name="info" />
    </button>
  );
}

export function CalcPanel({
  lines,
  totalLabel,
  total,
  note,
}: {
  lines: CalcLine[];
  totalLabel: string;
  total: string;
  note: string;
}) {
  const code = useCurrency();
  const grouping = useGrouping();
  const headingId = useId();
  const money = (value: string) => withCurrency(formatMoney(value, grouping), code);
  return (
    <section className={styles.calcPanel} aria-labelledby={headingId}>
      <h3 id={headingId}>How this is worked out</h3>
      {lines.map(({ label, amount, sign }) => {
        const flipped = amount.startsWith("-");
        const shown = flipped ? amount.slice(1) : amount;
        const plus = (sign === "+" && !flipped) || (sign === "−" && flipped);
        const lineClass = sign ? (plus ? styles.plus : styles.minus) : "";
        return (
          <p key={label} className={`${styles.calcLine} ${lineClass}`.trim()}>
            <span>{label}</span>
            <b>{money(shown)}</b>
          </p>
        );
      })}
      <p className={`${styles.calcLine} ${styles.calcTotal}`}>
        <span>{totalLabel}</span>
        <b>{money(total)}</b>
      </p>
      <p className={styles.calcNote}>{note}</p>
    </section>
  );
}
