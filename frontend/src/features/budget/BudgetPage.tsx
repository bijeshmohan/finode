// The Budgets page: Ready to assign with the sum behind it, Copy last month's amounts,
// a first-time welcome, the overspent warning, and the month's categories biggest budget first, each opening the sheet
// where its amount is set.
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { messageOf } from "../../api/messages";
import { useCurrency, useGrouping, useSymbol } from "../../app/currency";
import { useToday } from "../../app/session";
import { CalcButton, CalcPanel } from "../../components/CalcInfo";
import { Figure } from "../../components/Figure";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import { MonthPill } from "../../components/MonthPill";
import look from "../../components/Page.module.css";
import { monthName, shortDate } from "../../lib/dates";
import { formatMoney, withCurrency } from "../../lib/money";
import { positive } from "../../lib/split";
import styles from "./Budget.module.css";
import { BudgetRows } from "./BudgetRows";
import { CategorySheet } from "./CategorySheet";
import { type BudgetRow, type BudgetView, useBudget, useComingUp, useCopyLastMonth } from "./queries";

function ComingNote() {
  const grouping = useGrouping();
  const today = useToday();
  const coming = useComingUp(true);
  const found = coming.data;
  if (!found?.count) return null;
  return (
    <Link className={styles.coming} to="/budget/coming-up">
      <span>
        {found.count} {found.count === 1 ? "payment" : "payments"} coming up by {shortDate(found.through, today)}
        {found.total !== null && found.total !== undefined && (
          <>
            {" · "}
            <b>{formatMoney(found.total, grouping)}</b>
          </>
        )}
      </span>
      <span aria-hidden="true">›</span>
    </Link>
  );
}

function Head({ view }: { view: BudgetView }) {
  const grouping = useGrouping();
  const code = useCurrency();
  const symbol = useSymbol();
  const [explaining, setExplaining] = useState(false);
  const rta = view.ready_to_assign;
  const over = rta.startsWith("-");
  const name = `${monthName(view.month)} ${view.month.slice(0, 4)}`;
  return (
    <div className={look.hero}>
      <div className={look.heroTop}>
        <div className={styles.calcRow}>
          <span>Ready to assign</span>
          <CalcButton
            what="what is ready to assign"
            open={explaining}
            onToggle={() => {
              setExplaining((open) => !open);
            }}
          />
        </div>
      </div>
      <span className={look.figure} data-testid="ready-figure">
        <Figure value={positive(rta) ? rta : "0"} />
      </span>
      <span className={look.heroNote}>
        <span>
          {over ? (
            <span className={styles.heroWarn}>
              Over-assigned by {withCurrency(formatMoney(rta.slice(1), grouping), code)} · take some back from a
              category
            </span>
          ) : positive(rta) ? (
            "Give it a job: tap a category"
          ) : view.rows.length ? (
            `Every ${symbol} has a job`
          ) : (
            "Nothing to assign yet"
          )}
        </span>
      </span>
      {explaining && (
        <CalcPanel
          lines={[
            { label: "In your accounts", amount: view.sum.money_in_accounts, sign: "" },
            { label: "Set aside for card bills", amount: view.sum.reserved_for_cards, sign: "−" },
            { label: "Left in your categories", amount: view.sum.available, sign: "−" },
            { label: "Assigned to later months", amount: view.sum.assigned_to_later_months, sign: "−" },
          ]}
          totalLabel="Ready to assign"
          total={rta}
          note={`Money in your accounts that has no job yet, counted up to ${view.is_current ? "today" : `the end of ${name}`}.`}
        >
          {view.is_current && <ComingNote />}
        </CalcPanel>
      )}
    </div>
  );
}

export function BudgetPage() {
  const today = useToday();
  const grouping = useGrouping();
  const code = useCurrency();
  const symbol = useSymbol();
  const [params, setParams] = useSearchParams();
  const query = useBudget(params.get("month"));
  const copy = useCopyLastMonth();
  const [open, setOpen] = useState<BudgetRow | null>(null);
  const view = query.data;
  const month = view?.month ?? params.get("month") ?? today.slice(0, 7);

  return (
    <>
      <div className={look.pageHead}>
        <h1>Budgets</h1>
        <MonthPill
          month={month}
          onChange={(m) => {
            setParams(new URLSearchParams({ month: m }));
          }}
        />
      </div>
      {query.isError && <LoadError error={query.error} onRetry={() => void query.refetch()} />}
      {view && (
        <>
          <Head view={view} />
          {positive(view.copyable) && (
            <div className={styles.copy}>
              <button
                type="button"
                className={styles.quiet}
                disabled={copy.isPending}
                onClick={() => {
                  copy.mutate(view.month);
                }}
              >
                Copy last month&apos;s amounts · {formatMoney(view.copyable, grouping)}
              </button>
            </div>
          )}
          {view.show_intro && view.has_budget_accounts && (
            <div className={styles.intro}>
              <b>Give every {symbol} a job</b>
              <p>
                Decide how much of your money goes to rent, food and the rest. What you don&apos;t spend stays there for
                next month.
              </p>
              {view.rows.length ? (
                <span className={styles.introStep}>Tap a category below to set aside your first amount.</span>
              ) : (
                <Link className={styles.introStep} to="/categories/new?root=expense">
                  Start with your first category →
                </Link>
              )}
            </div>
          )}
          {positive(view.overspent) && (
            <div className={styles.warns}>
              <p className={styles.warn} role="alert">
                Overspent by {withCurrency(formatMoney(view.overspent, grouping), code)}
              </p>
            </div>
          )}
          {copy.isError && (
            <p className={look.error} role="alert">
              {messageOf(copy.error)}
            </p>
          )}
          {!view.has_budget_accounts && (
            <div className={look.empty}>
              <p>No account is part of the budget yet. Choose the accounts whose money you plan with.</p>
              <Link className={look.button} to="/accounts">
                Choose accounts
              </Link>
            </div>
          )}
          {view.rows.length > 0 ? (
            <BudgetRows rows={view.rows} onOpen={setOpen} />
          ) : (
            view.has_budget_accounts && (
              <div className={look.empty}>
                <p>There are no expense categories yet.</p>
                <Link className={look.button} to="/categories/new?root=expense">
                  <Icon name="plus" />
                  Add a category
                </Link>
              </div>
            )
          )}
          {open && (
            <CategorySheet
              row={open}
              month={view.month}
              monthName={`${monthName(view.month)} ${view.month.slice(0, 4)}`}
              onClose={() => {
                setOpen(null);
              }}
            />
          )}
        </>
      )}
    </>
  );
}
