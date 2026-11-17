// The rows of a budget: a category, or a group, with what is left, one quiet line ("of
// 25,000.00 · all spent · Fuel · Taxi") and a bar under both. How each reads is the server's (services/budget_view).
// A group opens its own page; a category opens the sheet where its amount is set.
import type { ReactNode } from "react";
import { Link } from "react-router";

import { useGrouping } from "../../app/currency";
import { formatMoney } from "../../lib/money";
import styles from "./Budget.module.css";
import type { BudgetRow } from "./queries";

function Inside({ row }: { row: BudgetRow }) {
  const grouping = useGrouping();
  const negative = row.available.startsWith("-");
  return (
    <>
      <span className={styles.main}>
        <span className={styles.name}>{row.name}</span>
        <span className={styles.sub}>
          {row.of !== null ? `of ${formatMoney(row.of, grouping)}` : "nothing assigned"}
          {row.state === "overspent" && (
            <>
              {" · "}
              <span className={styles.negative}>overspent</span>
            </>
          )}
          {row.state === "all_spent" && " · all spent"}
          {row.hint && ` · ${row.hint}`}
        </span>
      </span>
      <span className={styles.amount}>
        <span className={negative ? styles.negative : undefined}>{formatMoney(row.available, grouping)}</span>
      </span>
      <span className={row.over ? `${styles.bar} ${styles.over}` : styles.bar} aria-hidden="true">
        <i style={{ width: `${String(row.percent)}%` }} />
      </span>
    </>
  );
}

export function BudgetRows({
  rows,
  month,
  onOpen,
}: {
  rows: BudgetRow[];
  month: string;
  onOpen: (row: BudgetRow) => void;
}): ReactNode {
  return (
    <div className={styles.list}>
      {rows.map((r) =>
        r.is_group ? (
          <Link key={r.category_id} className={styles.row} to={`/budget/groups/${r.category_id}?month=${month}`}>
            <Inside row={r} />
          </Link>
        ) : (
          <button
            key={r.category_id}
            type="button"
            className={styles.row}
            onClick={() => {
              onOpen(r);
            }}
          >
            <Inside row={r} />
          </button>
        ),
      )}
    </div>
  );
}
