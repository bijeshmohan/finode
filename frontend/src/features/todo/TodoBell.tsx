// The to-do bell: a count in the top bar and the sidebar, and a sheet of what needs a decision (a card bill due, a
// recurring rule that could not be recorded), each item with its fix. What counts is the server's (services/todo.py).
import { useState } from "react";
import { Link } from "react-router";

import { messageOf } from "../../api/messages";

import { useCurrency, useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { Icon } from "../../components/Icon";
import { Sheet } from "../../components/Sheet";
import { shortDate } from "../../lib/dates";
import { formatMoney, withCurrency } from "../../lib/money";
import { type TodoView, useTodo } from "./queries";
import styles from "./Todo.module.css";

const plural = (n: number, one: string, many: string) => `${String(n)} ${n === 1 ? one : many}`;

function billSays(days: number): string {
  if (days < 0) return `overdue by ${plural(-days, "day", "days")}`;
  if (days === 0) return "due today";
  return `due in ${plural(days, "day", "days")}`;
}

function Items({ view, onLeave }: { view: TodoView; onLeave: () => void }) {
  const today = useToday();
  const grouping = useGrouping();
  const code = useCurrency();
  const money = (value: string) => formatMoney(value, grouping);
  return (
    <>
      {view.count === 0 ? (
        <p className={styles.empty}>Nothing needs you.</p>
      ) : (
        <div className={styles.list}>
          {view.card_bills.map((b) => (
            <div key={b.account_id} className={styles.item}>
              <strong>
                {b.name} bill is {billSays(b.days_to_due)}
              </strong>
              <p>
                {withCurrency(money(b.bill), code)} · due {shortDate(b.due_date, today)}
              </p>
              <Link
                className={styles.secondary}
                to={`/transactions/new?pay=${b.account_id}&amount=${b.bill}&back=/accounts/${b.account_id}`}
                onClick={onLeave}
              >
                Pay bill
              </Link>
            </div>
          ))}
          {view.failing_rules.map((r) => (
            <div key={r.recurring_id} className={styles.item}>
              <strong>{r.name} could not be recorded</strong>
              <p>{r.error}</p>
              <Link className={styles.secondary} to={`/recurring/${r.recurring_id}/edit`} onClick={onLeave}>
                Open rule
              </Link>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/** The bell: `bar` in the top bar (an icon with the count), `side` in the sidebar (with its name). */
export function TodoBell({ place }: { place: "bar" | "side" }) {
  const query = useTodo();
  const [open, setOpen] = useState(false);
  const count = query.data?.count ?? 0;
  const badge = count > 0 && <span className={styles.badge}>{count}</span>;
  return (
    <>
      {place === "bar" ? (
        <button
          type="button"
          className={styles.bar}
          title="To do"
          aria-label="To do"
          onClick={() => {
            setOpen(true);
          }}
        >
          <Icon name="bell" />
          {badge}
        </button>
      ) : (
        <button
          type="button"
          className={styles.side}
          onClick={() => {
            setOpen(true);
          }}
        >
          <Icon name="bell" />
          <span>To do</span>
          {badge}
        </button>
      )}
      {open && (
        <Sheet
          open
          title="To do"
          onClose={() => {
            setOpen(false);
          }}
        >
          {query.isError ? (
            <p className={styles.error} role="alert">
              {messageOf(query.error)}
            </p>
          ) : (
            query.data && (
              <Items
                view={query.data}
                onLeave={() => {
                  setOpen(false);
                }}
              />
            )
          )}
        </Sheet>
      )}
    </>
  );
}
