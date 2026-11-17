// One category in the sheet over the budget: what is left, what is assigned this month,
// what was spent, Save, and Move money.
import { useId, useState } from "react";
import { Link } from "react-router";

import { messageOf } from "../../api/messages";
import { useGrouping, usePlaces } from "../../app/currency";
import { AmountField } from "../../components/AmountField";
import { Sheet } from "../../components/Sheet";
import { groupAmount, tidyAmount } from "../../lib/amount";
import { formatMoney } from "../../lib/money";
import { positive, sameAmount } from "../../lib/split";
import styles from "./Budget.module.css";
import { type BudgetRow, useAssign } from "./queries";

export function SheetHead({ title, sub, available }: { title: string; sub: string; available: string }) {
  const grouping = useGrouping();
  return (
    <div className={styles.sheetTitle}>
      <div>
        <h2>{title}</h2>
        <p>{sub}</p>
      </div>
      <div className={available.startsWith("-") ? `${styles.sheetAmount} ${styles.over}` : styles.sheetAmount}>
        {formatMoney(available, grouping)}
        <small>left</small>
      </div>
    </div>
  );
}

interface SheetProps {
  row: BudgetRow;
  month: string;
  monthName: string;
  onClose: () => void;
}

export function CategorySheet({ row, month, monthName, onClose }: SheetProps) {
  const grouping = useGrouping();
  const places = usePlaces();
  const assign = useAssign();
  const id = useId();
  const [amount, setAmount] = useState(!sameAmount(row.assigned, "0") ? groupAmount(row.assigned, grouping) : "");
  return (
    <Sheet open onClose={onClose} title={row.name} showTitle={false}>
      <SheetHead
        title={row.name}
        sub={row.group_name ? `${monthName} · ${row.group_name}` : monthName}
        available={row.available}
      />
      <form
        className={styles.sheetForm}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          const plain = amount.trim() ? tidyAmount(amount, places).replace(/,/g, "") : "0";
          assign.mutate({ id: row.category_id, month, amount: plain }, { onSuccess: onClose });
        }}
      >
        <AmountField
          id={`${id}-assigned`}
          label="Assigned this month"
          value={amount}
          onChange={setAmount}
          places={places}
          grouping={grouping}
          // eslint-disable-next-line jsx-a11y-x/no-autofocus -- the sheet is opened to set this amount
          autoFocus
        />
        {assign.isError && (
          <p className={styles.sheetError} role="alert">
            {messageOf(assign.error)}
          </p>
        )}
        <dl className={styles.facts}>
          <div>
            <dt>Spent</dt>
            <dd>{formatMoney(row.activity, grouping)}</dd>
          </div>
          {positive(row.overspent_last_month) && (
            <div>
              <dt>Overspent last month</dt>
              <dd>{formatMoney(row.overspent_last_month, grouping)}</dd>
            </div>
          )}
        </dl>
        <div className={styles.actions}>
          <button type="submit" className={styles.save} disabled={assign.isPending} aria-busy={assign.isPending}>
            Save
          </button>
          <Link className={styles.moveLink} to={`/budget/move?month=${month}&source=${row.category_id}`}>
            Move money
          </Link>
        </div>
      </form>
    </Sheet>
  );
}
