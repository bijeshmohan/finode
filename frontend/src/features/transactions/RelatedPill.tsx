// The grey pill after a row's title when the entry is related to an earlier one (a refund, a reversal): the link glyph,
// that entry's date and amount. Tapping it opens the earlier entry's sheet, not the row's own.
import type { KeyboardEvent, MouseEvent } from "react";

import { Icon } from "../../components/Icon";
import { shortDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { useGrouping } from "../../app/currency";
import styles from "./TransactionList.module.css";
import type { Row } from "./queries";

export function RelatedPill({
  related,
  today,
  onOpen,
}: {
  related: NonNullable<Row["related"]>;
  today: string;
  onOpen: (id: string) => void;
}) {
  const grouping = useGrouping();
  const day = shortDate(related.date, today);
  function open(event: MouseEvent | KeyboardEvent) {
    event.stopPropagation();
    event.preventDefault();
    onOpen(related.id);
  }
  return (
    // Today's design: the pill sits inside the row, so it is a link of its own within the row's button.
    <span
      className={styles.pill}
      role="link"
      tabIndex={0}
      aria-label={`Related to an entry of ${day}`}
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") open(event);
      }}
    >
      <Icon name="link" />
      <span>
        {day} · {formatMoney(related.amount, grouping)}
      </span>
    </span>
  );
}
