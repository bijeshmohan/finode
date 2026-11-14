// One account as a card (partials/account_card.html): its name, its balance and, when there is something to say, one
// quiet line. Which line is the server's (a bill, no entries yet, none for a month); only its wording is here.
import { Link } from "react-router";

import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { Icon } from "../../components/Icon";
import { shortDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import styles from "./Accounts.module.css";
import type { AccountCardData } from "./queries";

function noteText(note: NonNullable<AccountCardData["note"]>, today: string): string {
  if (note.kind === "overdue") return "Bill overdue";
  if (note.kind === "due") return `Bill due ${note.on ? shortDate(note.on, today) : ""}`;
  if (note.kind === "empty") return "No entries yet";
  return `No entry since ${note.on ? shortDate(note.on, today) : ""}`;
}

/** `mark`: the pin shows in the corner (not in the Pinned row itself). */
export function AccountCard({ card, mark = true }: { card: AccountCardData; mark?: boolean }) {
  const grouping = useGrouping();
  const today = useToday();
  const pinned = mark && card.pinned && !card.closed;
  const note = card.closed ? null : card.note;
  const due = note !== null && (note.kind === "due" || note.kind === "overdue") && note.soon;
  return (
    <Link className={pinned ? `${styles.card} ${styles.pinned}` : styles.card} to={`/accounts/${card.id}`}>
      {pinned && (
        <span className={styles.pinMark} title="Pinned">
          <Icon name="pin" />
        </span>
      )}
      <span className={styles.cardName}>
        <span>{card.name}</span>
        {card.closed && <span className={styles.badge}>closed</span>}
        {card.on_budget && !card.closed && <i className={styles.dot} title="In the budget" />}
      </span>
      <span className={styles.cardFoot}>
        <span className={styles.cardBalance}>{formatMoney(card.balance, grouping)}</span>
        {note && (
          <span className={due ? `${styles.cardLine} ${styles.due}` : styles.cardLine}>{noteText(note, today)}</span>
        )}
      </span>
    </Link>
  );
}
