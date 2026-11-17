// The to-do bell: a count in the top bar and the sidebar, and a
// sheet of what needs a decision, each item with its fix. What counts is the server's (services/todo.py); the sheet
// stays open after a fix and redraws from the view.
import { useState } from "react";
import { Link } from "react-router";

import { messageOf } from "../../api/messages";
import { useCurrency, useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { Icon } from "../../components/Icon";
import { Sheet } from "../../components/Sheet";
import { shortDate } from "../../lib/dates";
import { formatMoney, withCurrency } from "../../lib/money";
import { type TodoView, useIncludeAccount, useLabelPayment, useTodo } from "./queries";
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
  const label = useLabelPayment();
  const include = useIncludeAccount();
  const money = (value: string) => formatMoney(value, grouping);
  const failed = label.error ?? include.error;
  return (
    <>
      {failed && (
        <p className={styles.error} role="alert">
          {messageOf(failed)}
        </p>
      )}
      {view.count === 0 ? (
        <p className={styles.empty}>Nothing needs you.</p>
      ) : (
        <div className={styles.list}>
          {view.uncategorised.length > 0 && (
            <div className={styles.item}>
              <strong>
                {view.uncategorised.length === 1
                  ? "1 payment has no category"
                  : `${String(view.uncategorised.length)} payments have no category`}
              </strong>
              <p>The money left the budget and no category paid for it.</p>
              <ul className={styles.payments}>
                {view.uncategorised.map((u) => {
                  const name = u.payee ?? u.account;
                  return (
                    <li key={u.transaction_id}>
                      <span>
                        {name}{" "}
                        <span className={styles.muted}>
                          · {shortDate(u.date, today)} · {money(u.amount)}
                        </span>
                      </span>
                      <select
                        aria-label={`Category for ${name}`}
                        value=""
                        disabled={label.isPending}
                        onChange={(event) => {
                          include.reset();
                          label.mutate({ transactionId: u.transaction_id, categoryId: event.target.value });
                        }}
                      >
                        <option value="">Choose category…</option>
                        {view.categories.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.path}
                          </option>
                        ))}
                      </select>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
          {view.left_out_accounts.map((a) => (
            <div key={a.account_id} className={styles.item}>
              <strong>{a.path} is not in the budget</strong>
              <p>
                {withCurrency(money(a.spent), code)} spent this month in {plural(a.entries, "entry", "entries")} is in
                no category.
              </p>
              <button
                type="button"
                className={styles.secondary}
                disabled={include.isPending}
                onClick={() => {
                  label.reset();
                  include.mutate(a.account_id);
                }}
              >
                Add to budget
              </button>
            </div>
          ))}
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
