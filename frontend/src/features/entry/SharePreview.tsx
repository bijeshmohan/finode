// What the Split would do, as typed so far (expense_preview.html, income_preview.html): the server's own figures, or
// why it cannot be saved yet.
import { messageOf } from "../../api/messages";
import { useGrouping } from "../../app/currency";
import { formatMoney } from "../../lib/money";
import { positive, sameAmount } from "../../lib/split";
import { type SharePreviewAsk, useSharePreview } from "./queries";
import styles from "./ShareEditor.module.css";

export function SharePreview({ ask }: { ask: SharePreviewAsk | null }) {
  const grouping = useGrouping();
  const preview = useSharePreview(ask);
  const money = (value: string) => formatMoney(value, grouping);
  const expense = preview.data?.expense;
  const income = preview.data?.income;
  return (
    <div className={styles.preview} aria-live="polite">
      {ask !== null && preview.isError && <p className={styles.error}>{messageOf(preview.error)}</p>}
      {ask !== null && !preview.isError && expense && (
        <>
          <ul className={styles.previewList}>
            {expense.shares.map((s) => (
              <li key={s.contact_id ?? "you"}>
                <span>{s.name}</span>
                <b>{money(s.share_amount)}</b>
              </li>
            ))}
          </ul>
          <p className={styles.previewHead}>After this</p>
          <ul className={styles.previewList}>
            <li>
              <span>
                Your share <span className={styles.muted}>(what your budget sees)</span>
              </span>
              <b>{money(expense.user_share)}</b>
            </li>
            {expense.owed.map((o) => (
              <li key={o.contact_id}>
                <span>
                  {o.name} {o.direction === "receivable" ? "owes you" : "is owed by you"}
                </span>
                <b className={o.direction === "receivable" ? styles.income : styles.out}>{money(o.amount)}</b>
              </li>
            ))}
          </ul>
          {!sameAmount(expense.unfunded, "0") && (
            <p className={styles.warn}>
              {positive(expense.unfunded)
                ? `${money(expense.unfunded)} of the bill has no payer yet. Say who paid the rest.`
                : `The payments are ${money(expense.unfunded.replace("-", ""))} more than the bill.`}
            </p>
          )}
        </>
      )}
      {ask !== null && !preview.isError && income && (
        <>
          <p className={styles.previewHead}>After this</p>
          <ul className={styles.previewList}>
            <li>
              <span>Your income</span>
              <b className={styles.income}>{money(income.your_income)}</b>
            </li>
            {income.theirs.map((p) => (
              <li key={`theirs-${p.contact_id}`}>
                <span>
                  {p.name} <span className={styles.muted}>(you hold it for them)</span>
                </span>
                <b className={styles.out}>{money(p.amount)}</b>
              </li>
            ))}
            {income.received_by.map((p) => (
              <li key={`got-${p.contact_id}`}>
                <span>{p.name} owes you</span>
                <b className={styles.income}>{money(p.amount)}</b>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
