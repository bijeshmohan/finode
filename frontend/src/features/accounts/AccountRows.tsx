// Accounts as a list: one row each (the shared Row: the name, one quiet line when there is something to say, the
// balance at the right) in one tile, ending in a line to add another. Which quiet line is the server's (a bill, no
// entries yet, none for a month); only its wording is here. Nothing scrolls sideways.
import { Link } from "react-router";

import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { Icon } from "../../components/Icon";
import { Row } from "../../components/Row";
import { shortDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import look from "../../components/Page.module.css";
import styles from "./Accounts.module.css";
import type { AccountCardData } from "./queries";

function noteText(note: NonNullable<AccountCardData["note"]>, today: string): string {
  if (note.kind === "overdue") return "Bill overdue";
  if (note.kind === "due") return `Bill due ${note.on ? shortDate(note.on, today) : ""}`;
  if (note.kind === "empty") return "No entries yet";
  return `No entry since ${note.on ? shortDate(note.on, today) : ""}`;
}

function AccountRow({ card, withIcon }: { card: AccountCardData; withIcon: boolean }) {
  const grouping = useGrouping();
  const today = useToday();
  const note = card.closed ? null : card.note;
  const due = note !== null && (note.kind === "due" || note.kind === "overdue") && note.soon;
  return (
    <Row
      to={`/accounts/${card.id}`}
      icon={withIcon ? (card.icon ?? undefined) : undefined}
      title={
        <>
          {card.name}
          {card.closed && (
            <>
              {" "}
              <span className={look.badge}>closed</span>
            </>
          )}
        </>
      }
      detail={note ? <span className={due ? styles.due : undefined}>{noteText(note, today)}</span> : undefined}
      figure={formatMoney(card.balance, grouping)}
    />
  );
}

/** `withIcons`: each row leads with its type's icon (where the types are mixed, as in Pinned); under a type's heading
 * the heading carries it once. `add`: the line that adds an account of the type. */
export function AccountRows({
  cards,
  withIcons = false,
  add,
}: {
  cards: AccountCardData[];
  withIcons?: boolean;
  add?: { to: string; label: string };
}) {
  return (
    <ul className={styles.list}>
      {cards.map((c) => (
        <li key={c.id}>
          <AccountRow card={c} withIcon={withIcons} />
        </li>
      ))}
      {add && (
        <li>
          <Link className={styles.addLine} to={add.to}>
            <Icon name="plus" />
            {add.label}
          </Link>
        </li>
      )}
    </ul>
  );
}
