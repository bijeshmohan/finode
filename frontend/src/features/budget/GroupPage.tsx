// One group's budget: what is left in it and how much of what there was is
// spent, its categories each opening the sheet, and its own budget in a sheet that never goes below what its
// categories add up to.
import { useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router";

import { useGrouping, usePlaces } from "../../app/currency";
import { AmountField } from "../../components/AmountField";
import { Figure } from "../../components/Figure";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import { MonthPill } from "../../components/MonthPill";
import look from "../../components/Page.module.css";
import { Sheet } from "../../components/Sheet";
import { groupAmount, tidyAmount } from "../../lib/amount";
import { monthName } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { less, sameAmount } from "../../lib/split";
import { messageOf } from "../../api/messages";
import categoryStyles from "../../components/Rows.module.css";
import styles from "./Budget.module.css";
import { BudgetRows } from "./BudgetRows";
import { CategorySheet, SheetHead } from "./CategorySheet";
import { type BudgetGroupView, type BudgetRow, useAssignGroup, useBudgetGroup } from "./queries";

function GroupSheet({ view, monthLabel, onClose }: { view: BudgetGroupView; monthLabel: string; onClose: () => void }) {
  const grouping = useGrouping();
  const places = usePlaces();
  const assign = useAssignGroup();
  const [amount, setAmount] = useState(!sameAmount(view.assigned, "0") ? groupAmount(view.assigned, grouping) : "");
  const below = less(amount.trim() ? amount : "0", view.minimum);
  return (
    <Sheet open onClose={onClose} title={view.name} showTitle={false}>
      <SheetHead title={view.name} sub={monthLabel} available={view.glance.left} />
      <form
        className={styles.sheetForm}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (below) return; // red: below what its categories add up to, nothing is saved
          const total = amount.trim() ? tidyAmount(amount, places).replace(/,/g, "") : "0";
          assign.mutate({ id: view.id, month: view.month, total }, { onSuccess: onClose });
        }}
      >
        <AmountField
          id="group-assigned"
          label="Assigned this month"
          value={amount}
          onChange={setAmount}
          places={places}
          grouping={grouping}
          invalid={below}
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
            <dd>{formatMoney(view.glance.spent, grouping)}</dd>
          </div>
        </dl>
        <div className={styles.actions}>
          <button type="submit" className={styles.save} disabled={assign.isPending} aria-busy={assign.isPending}>
            Save
          </button>
        </div>
      </form>
    </Sheet>
  );
}

export function GroupPage() {
  const { categoryId = "" } = useParams();
  const grouping = useGrouping();
  const [params, setParams] = useSearchParams();
  const query = useBudgetGroup(categoryId, params.get("month"));
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState<BudgetRow | null>(null);
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  const view = query.data;
  if (!view) return <h1 className="sr-only">Budgets</h1>;
  const g = view.glance;
  const over = g.left.startsWith("-");
  const label = `${monthName(view.month)} ${view.month.slice(0, 4)}`;
  const barLabel =
    `${String(g.percent)}% of what there was to spend is spent` +
    (view.pace !== null ? `, and ${String(view.pace)}% of the month has passed` : "");
  return (
    <>
      <div className={categoryStyles.nav}>
        <Link className={look.back} to={`/budget?month=${view.month}`}>
          <Icon name="back" />
          Budgets
        </Link>
        <MonthPill
          month={view.month}
          onChange={(m) => {
            setParams(new URLSearchParams({ month: m }));
          }}
        />
      </div>
      <h1 className={styles.groupTitle}>{view.name}</h1>
      <button
        type="button"
        className={styles.tappable}
        title="Set the budget"
        onClick={() => {
          setEditing(true);
        }}
      >
        <span className="sr-only">Left to spend</span>
        {over && <span className={look.muted}>Over budget</span>}
        <span className={over ? `${look.figure} ${styles.over}` : look.figure}>
          <Figure value={g.left} />
        </span>
        <span className={styles.glanceBar} role="img" aria-label={barLabel}>
          <i style={{ width: `${String(g.percent)}%` }} />
          {view.pace !== null && <b className={styles.pace} style={{ left: `${String(view.pace)}%` }} />}
        </span>
        <span className={look.heroNote}>
          <span>
            {g.planned
              ? `Spent ${formatMoney(g.spent, grouping)} of ${formatMoney(g.of, grouping)}`
              : "Nothing assigned yet"}
          </span>
          <span className={styles.chev} aria-hidden="true">
            <Icon name="back" />
          </span>
        </span>
      </button>
      <BudgetRows rows={view.kids} month={view.month} onOpen={setOpen} />
      {editing && (
        <GroupSheet
          view={view}
          monthLabel={label}
          onClose={() => {
            setEditing(false);
          }}
        />
      )}
      {open && (
        <CategorySheet
          row={open}
          month={view.month}
          monthName={label}
          onClose={() => {
            setOpen(null);
          }}
        />
      )}
    </>
  );
}

/** /budget/group/:id, an old address, opens the same page. */
export function OldGroupAddress() {
  const { categoryId = "" } = useParams();
  const [params] = useSearchParams();
  const search = params.toString();
  return <Navigate to={`/budget/groups/${categoryId}${search ? `?${search}` : ""}`} replace />;
}
