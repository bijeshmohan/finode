// The entries on an account's or a category's own page, by day, newest first (account_entries.html,
// category_entries.html). How each row reads is the server's (services/transaction_rows.RegisterRow): green and "+" for
// money coming in, "−" for a category's line that went the other way, the running balance small beneath on an account.
import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import type { components } from "../../api/schema";
import { Icon } from "../../components/Icon";
import { Row } from "../../components/Row";
import { friendlyDate, shortDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import styles from "./RegisterList.module.css";
import { RelatedPill } from "./RelatedPill";
import listStyles from "./TransactionList.module.css";

export type RegisterRow = components["schemas"]["RegisterRowRead"];

interface RegisterProps {
  rows: RegisterRow[];
  onOpen: (id: string) => void;
}

export function RegisterList({ rows, onOpen }: RegisterProps) {
  const today = useToday();
  const grouping = useGrouping();
  const byDay = new Map<string, RegisterRow[]>();
  for (const row of rows) byDay.set(row.date, [...(byDay.get(row.date) ?? []), row]);
  const ordered = [...byDay.entries()].sort(([a], [b]) => (a < b ? 1 : -1));
  return (
    <div className={listStyles.list}>
      {ordered.map(([day, items]) => (
        <section key={day}>
          <h3 className={listStyles.dayHead}>
            <span>{friendlyDate(day, today)}</span>
          </h3>
          <ul className={listStyles.tile}>
            {items.map((row) => (
              <li key={row.id}>
                <Row
                  title={
                    <span className={row.related ? listStyles.titleWithPill : undefined}>
                      <span className={listStyles.titleText}>{row.title}</span>
                      {row.related && <RelatedPill related={row.related} today={today} onOpen={onOpen} />}
                    </span>
                  }
                  detail={row.sub}
                  extra={
                    row.posts_on && (
                      <span className={styles.posts}>
                        <Icon name="calendar" />
                        Posts {shortDate(row.posts_on, today)}
                      </span>
                    )
                  }
                  figure={
                    <span className={styles.amount}>
                      <span>
                        {row.negative ? "−" : ""}
                        {formatMoney(row.amount, grouping)}
                      </span>
                      {row.balance !== null && <small>{formatMoney(row.balance, grouping)}</small>}
                    </span>
                  }
                  figureTone={row.inflow ? "in" : "plain"}
                  onClick={() => {
                    onOpen(row.id);
                  }}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
