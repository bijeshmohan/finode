// Home (dashboard.html): the month's budget at a glance, a new person's first steps, and the month's entries, a few
// first and "Show more" for the rest. The month and an open entry live in the address.
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { MonthPill } from "../../components/MonthPill";
import { formatMoney } from "../../lib/money";
import { TransactionList } from "../transactions/TransactionList";
import { TransactionSheet } from "../transactions/TransactionSheet";
import { useOpenEntry } from "../transactions/useOpenEntry";
import { CalcButton, CalcPanel } from "./CalcInfo";
import { Figure } from "./Figure";
import { GetStarted } from "./GetStarted";
import styles from "./Home.module.css";
import { HOME_MORE, type HomeView, useHome, useHomeMore } from "./queries";

const MONTH_NAMES = [
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

function monthName(month: string): string {
  return MONTH_NAMES[Number(month.slice(5, 7)) - 1] ?? "";
}

function Glance({ view, onMonth }: { view: HomeView; onMonth: (month: string) => void }) {
  const today = useToday();
  const grouping = useGrouping();
  const [explaining, setExplaining] = useState(false);
  const g = view.glance;
  const over = g.left.startsWith("-");
  const name = monthName(view.month);
  const spentWord = view.is_current ? "Spent so far" : "Spent";
  const barLabel =
    `${String(g.percent)}% of what there was to spend is spent` +
    (g.pace !== null ? `, and ${String(g.pace)}% of the month has passed` : "");

  return (
    <section className={styles.glance}>
      <div className={styles.boxTop}>
        {g.has_budget ? (
          <div className={styles.calcRow}>
            <p className={styles.glanceLabel}>{over ? "Over budget" : "Left to spend"}</p>
            <CalcButton
              what="what is left to spend"
              open={explaining}
              onToggle={() => {
                setExplaining((open) => !open);
              }}
            />
          </div>
        ) : (
          <p className={styles.glanceLabel}>Spent</p>
        )}
        <MonthPill month={view.month} max={today.slice(0, 7)} onChange={onMonth} />
      </div>
      {g.has_budget ? (
        <>
          <p className={`${styles.glanceFigure} ${over ? styles.over : ""}`.trim()} data-testid="glance-figure">
            <Figure value={g.left} />
          </p>
          <div className={styles.glanceBar} role="img" aria-label={barLabel}>
            <i style={{ width: `${String(g.percent)}%` }} />
            {g.pace !== null && <b className={styles.pace} style={{ left: `${String(g.pace)}%` }} />}
          </div>
          <p className={styles.glanceCaption}>
            {spentWord} {formatMoney(g.spent, grouping)} of {formatMoney(g.of, grouping)}
          </p>
          {explaining && (
            <CalcPanel
              lines={[
                { label: "Carried in from earlier months", amount: g.carried, sign: "" },
                { label: `Assigned in ${name}`, amount: g.assigned, sign: "+" },
                { label: spentWord, amount: g.spent, sign: "−" },
              ]}
              totalLabel="Left to spend"
              total={g.left}
              note="Each category's leftover, plus what you assigned this month, minus what you spent."
            />
          )}
        </>
      ) : (
        <>
          <p className={styles.glanceFigure} data-testid="glance-figure">
            <Figure value={view.spent} />
          </p>
          <p className={styles.glanceNote}>
            <Link to={`/budget?month=${view.month}`}>Set up your budget</Link> to see what is left to spend
          </p>
        </>
      )}
    </section>
  );
}

export function Home() {
  const [params, setParams] = useSearchParams();
  const asked = params.get("month") ?? undefined;
  const home = useHome(asked);
  const [openId, openEntry, closeEntry] = useOpenEntry();
  const [wantMore, setWantMore] = useState(false);
  const view = home.data;
  const more = useHomeMore(view?.month ?? "", view?.rows.length ?? 0, wantMore && Boolean(view));

  if (!view) return <h1 className="sr-only">Home</h1>;
  const name = monthName(view.month);
  const extra = more.data?.pages ?? [];
  const rows = [...view.rows, ...extra.flatMap((p) => p.rows)];
  const days = [...view.days, ...extra.flatMap((p) => p.days)];
  const left = view.total - rows.length;
  const steps = view.steps;
  const toMonth = (month: string) => {
    setWantMore(false);
    setParams({ month });
  };

  return (
    <>
      <h1 className="sr-only">Home</h1>
      <div className={styles.cols}>
        {!view.has_recorded ? (
          <section className={styles.empty}>
            <p className={styles.glanceLabel}>{name}</p>
            <p className={styles.headline}>Nothing recorded yet.</p>
            <p className={styles.muted}>Add your first transaction and this page starts to fill in.</p>
            {steps && (
              <>
                <p className={styles.sectionLabel}>
                  Get started · {view.steps_done} of {view.steps_total}
                </p>
                <GetStarted steps={steps} />
                <p className={`${styles.muted} ${styles.smallPrint}`}>
                  Already keep a ledger file? <Link to="/settings/data#import">Import it</Link>
                </p>
              </>
            )}
          </section>
        ) : (
          <>
            <Glance view={view} onMonth={toMonth} />
            {steps && (
              <section className={styles.getStarted}>
                <p className={styles.sectionLabel}>
                  Get started · {view.steps_done} of {view.steps_total}
                </p>
                <GetStarted steps={steps} />
              </section>
            )}
            <div className={styles.recent}>
              <div className={styles.sectionHead}>
                <h2>Transactions</h2>
                <Link className={styles.quietLink} to={`/transactions?month=${view.month}`}>
                  View all ›
                </Link>
              </div>
              {rows.length > 0 ? (
                <>
                  <TransactionList rows={rows} days={days} onOpen={openEntry} />
                  {left > 0 ? (
                    <div className={styles.more}>
                      <button
                        type="button"
                        className={styles.moreRow}
                        disabled={more.isFetching}
                        onClick={() => {
                          if (wantMore) void more.fetchNextPage();
                          else setWantMore(true);
                        }}
                      >
                        <span>Show {Math.min(HOME_MORE, left)} more</span>
                        <small>{left} left</small>
                      </button>
                    </div>
                  ) : (
                    extra.length > 0 && (
                      <p className={styles.end}>
                        That is all of {name} · {view.total} transaction{view.total === 1 ? "" : "s"}
                      </p>
                    )
                  )}
                </>
              ) : (
                <p className={styles.muted}>Nothing was recorded in {name}.</p>
              )}
            </div>
          </>
        )}
      </div>
      {openId && <TransactionSheet key={openId} id={openId} onClose={closeEntry} onOpen={openEntry} />}
    </>
  );
}
