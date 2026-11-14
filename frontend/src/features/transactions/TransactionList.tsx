// A list of transactions in day sections, newest first (partials/transaction_days.html). How each row names itself is
// the server's (services/transaction_rows.py); several opening balances on one day fold into one quiet row.
import { useToday } from "../../app/session";
import { useGrouping } from "../../app/currency";
import { Icon } from "../../components/Icon";
import { Row as ListRow } from "../../components/Row";
import { friendlyDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import type { DayTotal, Row } from "./queries";
import { RelatedPill } from "./RelatedPill";
import styles from "./TransactionList.module.css";

interface ListProps {
  rows: Row[];
  /** What each day with more than one entry spent, as the server added it up. */
  days?: DayTotal[];
  onOpen: (id: string) => void;
}

function Entry({ row, today, onOpen }: { row: Row; today: string; onOpen: (id: string) => void }) {
  const grouping = useGrouping();
  return (
    <li className={row.is_system ? styles.system : undefined}>
      <ListRow
        title={
          <span className={row.related ? styles.titleWithPill : undefined}>
            <span className={styles.titleText}>{row.title}</span>
            {row.related && <RelatedPill related={row.related} today={today} onOpen={onOpen} />}
          </span>
        }
        detail={row.sub}
        extra={
          <>
            {row.recurring && (
              <span className={styles.via}>
                <Icon name="repeat" />
                Recurring
              </span>
            )}
            {row.by_assistant && (
              <span className={styles.via}>
                <Icon name="robot" />
                {row.by_assistant}
              </span>
            )}
          </>
        }
        figure={formatMoney(row.amount, grouping)}
        figureTone={row.kind === "income" ? "in" : "plain"}
        onClick={() => {
          onOpen(row.id);
        }}
      />
    </li>
  );
}

export function TransactionList({ rows, days = [], onOpen }: ListProps) {
  const today = useToday();
  const grouping = useGrouping();
  const spent = new Map(days.map((d) => [d.date, d.spent]));
  const byDay = new Map<string, Row[]>();
  for (const row of rows) byDay.set(row.date, [...(byDay.get(row.date) ?? []), row]);
  const ordered = [...byDay.entries()].sort(([a], [b]) => (a < b ? 1 : -1));

  return (
    <div className={styles.list}>
      {ordered.map(([day, items]) => {
        const openings = items.filter((r) => r.is_opening);
        const fold = openings.length > 1;
        const total = spent.get(day);
        return (
          <section key={day}>
            <h3 className={styles.dayHead}>
              <span>{friendlyDate(day, today)}</span>
              {total !== undefined && <span className={styles.dayTotal}>Spent {formatMoney(total, grouping)}</span>}
            </h3>
            <ul className={styles.tile}>
              {items
                .filter((r) => !(fold && r.is_opening))
                .map((r) => (
                  <Entry key={r.id} row={r} today={today} onOpen={onOpen} />
                ))}
              {fold && (
                <li className={styles.fold}>
                  <details>
                    <summary>
                      <span className={styles.foldMain}>
                        <span className={styles.foldTitle}>Opening balances</span>
                        <span className={styles.foldSub}>{openings.length} accounts</span>
                      </span>
                      <Icon name="chevron-right" />
                    </summary>
                    <ul>
                      {openings.map((r) => (
                        <Entry key={r.id} row={r} today={today} onOpen={onOpen} />
                      ))}
                    </ul>
                  </details>
                </li>
              )}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
