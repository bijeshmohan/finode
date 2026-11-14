// Entries dated ahead, in one card (partials/upcoming.html): closed, a line with what they come to; open, the list
// with the date down the left. A row opens the entry's details.
import { useGrouping } from "../../app/currency";
import { Icon } from "../../components/Icon";
import { formatMoney } from "../../lib/money";
import type { TransactionsView } from "./queries";
import styles from "./TransactionsPage.module.css";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface CardProps {
  items: TransactionsView["upcoming"];
  total: string | null;
  open: boolean;
  onOpen: (id: string) => void;
}

export function UpcomingCard({ items, total, open, onOpen }: CardProps) {
  const grouping = useGrouping();
  return (
    <details className={styles.upcoming} open={open}>
      <summary>
        <span>
          {items.length} upcoming
          {total !== null && <span className={styles.upSub}> · {formatMoney(total, grouping)} in all</span>}
        </span>
        <span className={styles.caret}>
          <Icon name="caret" />
        </span>
      </summary>
      <ul className={styles.upList}>
        {items.map((it) => {
          const [, month = "1", day = "1"] = it.date.split("-");
          return (
            <li key={it.id}>
              <button
                type="button"
                className={styles.upRow}
                onClick={() => {
                  onOpen(it.id);
                }}
              >
                <span className={styles.upDate}>
                  <b>{Number(day)}</b>
                  <span>{MONTHS[Number(month) - 1]}</span>
                </span>
                <span className={styles.upMain}>
                  <span className={styles.upTitle}>{it.title}</span>
                  <span className={styles.upSubLine}>{it.sub}</span>
                </span>
                <span className={it.income ? styles.income : undefined}>
                  {it.income ? "+" : ""}
                  {formatMoney(it.amount, grouping)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
