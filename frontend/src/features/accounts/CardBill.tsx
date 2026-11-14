// A card's (or loan's) bill under its balance (partials/card_bill.html): what is left to pay of the latest statement and
// when, with Pay bill; or, without the days set, how to see it.
import { Link } from "react-router";

import { useCurrency, useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { shortDate } from "../../lib/dates";
import { formatMoney, withCurrency } from "../../lib/money";
import { positive, sameAmount } from "../../lib/split";
import look from "../../components/Page.module.css";
import styles from "./Accounts.module.css";
import type { AccountView } from "./queries";

function dueText(due: number, dueDate: string, today: string): string {
  if (due < 0) return `Overdue by ${String(-due)} day${due === -1 ? "" : "s"}`;
  if (due === 0) return "Due today";
  if (due <= 5) return `Due in ${String(due)} day${due === 1 ? "" : "s"}`;
  return `Due ${shortDate(dueDate, today)}`;
}

export function CardBill({ view }: { view: AccountView }) {
  const grouping = useGrouping();
  const code = useCurrency();
  const today = useToday();
  const money = (value: string) => formatMoney(value, grouping);
  const bill = view.bill;
  if (!bill) {
    if (!view.can_set_days) return null;
    return (
      <section className={styles.bill} aria-label="Bill">
        <p className={styles.billLabel}>Bill</p>
        <p className={look.muted}>Add the statement and due days to see what is due and when.</p>
        <Link className={`${styles.billPay} ${styles.quiet}`} to={`/accounts/${view.id}/edit`}>
          Add the days
        </Link>
      </section>
    );
  }
  const owing = positive(bill.bill);
  const dueClass = owing && bill.days_to_due < 0 ? styles.over : view.bill_soon ? styles.warn : "";
  return (
    <section className={styles.bill} aria-label="Bill">
      <div className={styles.billTop}>
        <div>
          <p className={styles.billLabel}>Bill</p>
          <p className={styles.billFigure}>
            {owing ? withCurrency(money(bill.bill), code) : positive(bill.statement_balance) ? "Paid" : "Nothing due"}
          </p>
        </div>
        <p className={`${styles.billDue} ${dueClass}`.trim()}>
          {owing
            ? dueText(bill.days_to_due, bill.due_date, today)
            : `Next statement ${shortDate(bill.next_statement_date, today)}`}
        </p>
      </div>
      {(positive(bill.statement_balance) || positive(bill.spent_since)) && (
        <dl className={styles.billRows}>
          {positive(bill.statement_balance) && (
            <div>
              <dt>Statement of {shortDate(bill.statement_date, today)}</dt>
              <dd>{money(bill.statement_balance)}</dd>
            </div>
          )}
          {!sameAmount(bill.rounded_by, "0") && (
            <div>
              <dt>Rounded</dt>
              <dd>
                {positive(bill.rounded_by) ? "+" : "−"}
                {money(bill.rounded_by.replace("-", ""))}
              </dd>
            </div>
          )}
          {positive(bill.paid_since) && (
            <div>
              <dt>Paid since</dt>
              <dd>−{money(bill.paid_since)}</dd>
            </div>
          )}
          {positive(bill.spent_since) && (
            <div>
              <dt>Spent since the statement</dt>
              <dd>{money(bill.spent_since)}</dd>
            </div>
          )}
        </dl>
      )}
      {owing && (
        <Link
          className={styles.billPay}
          to={`/transactions/new?pay=${view.id}&amount=${bill.bill}&back=/accounts/${view.id}`}
        >
          Pay bill
        </Link>
      )}
    </section>
  );
}
