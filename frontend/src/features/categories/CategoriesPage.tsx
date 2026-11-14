// The Categories page (categories.html): one month, Spending or Earning, what each category came to, biggest first, with
// the biggest inside it and its share of the month. The month and the tab live in the address.
import { Link, useSearchParams } from "react-router";

import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { Chips } from "../../components/Chips";
import { Figure } from "../../components/Figure";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import { MonthPill } from "../../components/MonthPill";
import look from "../../components/Page.module.css";
import { formatMoney } from "../../lib/money";
import { positive, sameAmount } from "../../lib/split";
import styles from "./Categories.module.css";
import { type CategoriesView, useCategories } from "./queries";

export const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export function monthName(month: string): string {
  return MONTH_NAMES[Number(month.slice(5, 7)) - 1] ?? "";
}

const TABS = [
  { value: "expense", label: "Spending" },
  { value: "income", label: "Earning" },
] as const;

function Rows({ view }: { view: CategoriesView }) {
  const grouping = useGrouping();
  const earning = view.tab === "income";
  return (
    <div className={styles.tile}>
      {view.rows.map((r) => {
        const empty = sameAmount(r.total, "0");
        const sub = empty
          ? "Nothing yet"
          : r.hint
            ? `${r.hint}${r.share ? ` · ${r.share}` : ""}`
            : r.share
              ? `${r.share} of ${earning ? "earnings" : "spending"}`
              : "";
        return (
          <Link key={r.id} className={styles.row} to={`/categories/${r.id}?month=${view.month}`}>
            <span className={styles.main}>
              <span className={styles.name}>{r.name}</span>
              <span className={styles.rowSub}>{sub}</span>
            </span>
            <span className={styles.amount}>
              {empty ? (
                <span className={styles.dash}>–</span>
              ) : (
                <span className={earning && positive(r.total) ? styles.income : undefined}>
                  {formatMoney(r.total, grouping)}
                </span>
              )}
            </span>
          </Link>
        );
      })}
    </div>
  );
}

export function CategoriesPage() {
  const today = useToday();
  const [params, setParams] = useSearchParams();
  const month = params.get("month");
  const tab = params.get("tab") === "income" ? "income" : "expense";
  const view = useCategories(month, tab);
  const shown = view.data?.month ?? month ?? today.slice(0, 7);
  const go = (next: { month?: string; tab?: string }) => {
    setParams(new URLSearchParams({ month: next.month ?? shown, tab: next.tab ?? tab }));
  };
  const page = view.data;
  const label =
    (tab === "income" ? "Earned" : "Spent") + (page && !page.is_current ? ` in ${monthName(shown)}` : " so far");
  return (
    <>
      <div className={look.pageHead}>
        <h1>Categories</h1>
        <MonthPill
          month={shown}
          max={today.slice(0, 7)}
          onChange={(m) => {
            go({ month: m });
          }}
        />
      </div>
      <div className={styles.catBar}>
        <Chips
          label="What to show"
          options={TABS}
          value={tab}
          onChange={(t) => {
            go({ tab: t });
          }}
        />
      </div>
      {view.isError && <LoadError error={view.error} onRetry={() => void view.refetch()} />}
      {page && (
        <>
          <div className={look.hero}>
            <div className={look.heroTop}>
              <span>{label}</span>
            </div>
            <span className={look.figure}>
              <Figure value={page.grand} />
            </span>
            <span className={look.heroNote}>
              <span>
                {page.rows.length
                  ? `${String(page.rows.length)} categor${page.rows.length === 1 ? "y" : "ies"}`
                  : "No categories yet"}
              </span>
            </span>
          </div>
          {page.rows.length ? (
            <>
              <Rows view={page} />
              <Link className={look.addRow} to={`/categories/new?root=${tab}`}>
                <Icon name="plus" />
                Add category
              </Link>
            </>
          ) : (
            <div className={look.empty}>
              <p>No {tab === "income" ? "earning" : "spending"} categories yet.</p>
              <Link className={look.button} to={`/categories/new?root=${tab}`}>
                Add a category
              </Link>
            </div>
          )}
        </>
      )}
    </>
  );
}
