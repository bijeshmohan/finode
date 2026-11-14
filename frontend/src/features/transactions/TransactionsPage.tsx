// The Transactions page (transactions.html): one month, newest first; the line that says how many and, filtered, what
// they come to; the Filter sheet; what is dated ahead in its own card; "Show more" for the rest of the month. The
// month, the filters and an open entry live in the address.
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { EmptyState } from "../../components/EmptyState";
import { LoadError } from "../../components/LoadError";
import { Icon } from "../../components/Icon";
import { MonthPill } from "../../components/MonthPill";
import { formatMoney } from "../../lib/money";
import { type Chosen, FilterSheet, type FilterKey } from "./FilterSheet";
import { type ListFilters, PAGE_SIZE, useTransactionsPages } from "./queries";
import { TransactionList } from "./TransactionList";
import styles from "./TransactionsPage.module.css";
import { TransactionSheet } from "./TransactionSheet";
import { UpcomingCard } from "./UpcomingCard";
import { useOpenEntry } from "./useOpenEntry";

const KEYS = ["account", "category", "merchant", "tag", "q", "kind"] as const;
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

function filtersOf(params: URLSearchParams, thisMonth: string): ListFilters {
  const filters: ListFilters = { month: params.get("month") ?? thisMonth };
  for (const key of KEYS) {
    const value = params.get(key);
    if (value) filters[key] = value;
  }
  return filters;
}

export function TransactionsPage() {
  const today = useToday();
  const thisMonth = today.slice(0, 7);
  const grouping = useGrouping();
  const [params, setParams] = useSearchParams();
  const filters = filtersOf(params, thisMonth);
  const list = useTransactionsPages(filters);
  const [openId, openEntry, closeEntry] = useOpenEntry();
  const [filtering, setFiltering] = useState(false);

  const pages = list.data?.pages ?? [];
  const first = pages[0];
  const rows = pages.flatMap((p) => p.rows);
  const days = pages.flatMap((p) => p.days);
  const searching = Boolean(
    filters.q ?? filters.kind ?? filters.account ?? filters.category ?? filters.merchant ?? filters.tag,
  );
  const month = first?.month ?? filters.month ?? thisMonth;

  /** This page's address with some filters changed (an empty value drops it). */
  function addressWith(changes: Partial<Record<(typeof KEYS)[number] | "month", string>>): string {
    const next = new URLSearchParams();
    next.set("month", month);
    for (const key of KEYS) {
      const value = key in changes ? changes[key] : filters[key];
      if (value) next.set(key, value);
    }
    if (changes.month) next.set("month", changes.month);
    return `/transactions?${next.toString()}`;
  }

  const applied = first?.applied ?? [];
  const chosen: Chosen = Object.fromEntries(applied.map((a) => [a.key, { value: filters[a.key] ?? "", name: a.name }]));

  return (
    <>
      <div className={styles.head}>
        <h1>Transactions</h1>
        <MonthPill
          month={month}
          max={thisMonth}
          onChange={(m) => {
            setParams(new URLSearchParams(addressWith({ month: m }).split("?")[1]));
          }}
        />
      </div>
      {list.isError && !first && <LoadError error={list.error} onRetry={() => void list.refetch()} />}
      {first?.error && (
        <p className={styles.error} role="alert">
          {first.error}
        </p>
      )}

      <div className={styles.filterbar}>
        <span className={styles.summary} data-testid="summary">
          {first?.summary ? (
            <>
              <b>{first.summary.count}</b> transaction{first.summary.count === 1 ? "" : "s"}
              {first.summary.total !== null && ` · ${formatMoney(first.summary.total, grouping)} ${first.summary.word}`}
            </>
          ) : first && first.total > 0 ? (
            <>
              <b>{first.total}</b> transaction{first.total === 1 ? "" : "s"}
            </>
          ) : (
            first && "No transactions"
          )}
        </span>
        <button
          type="button"
          className={styles.filterOpen}
          onClick={() => {
            setFiltering(true);
          }}
        >
          <Icon name="filter" />
          {applied.length ? `Filter · ${String(applied.length)}` : "Filter"}
        </button>
      </div>
      {applied.length > 0 && (
        <p className={styles.applied}>
          {applied.map((a) => (
            <Link
              key={a.key}
              to={addressWith({ [a.key]: "" })}
              aria-label={`Remove the ${a.label.toLowerCase()} filter`}
            >
              <b>{a.name}</b> <span aria-hidden="true">✕</span>
            </Link>
          ))}
        </p>
      )}

      {first && first.upcoming.length > 0 && (
        <UpcomingCard
          items={first.upcoming}
          total={first.upcoming_total}
          open={searching && rows.length === 0}
          onOpen={openEntry}
        />
      )}

      {rows.length > 0 ? (
        <>
          <TransactionList rows={rows} days={days} onOpen={openEntry} />
          {list.hasNextPage ? (
            <div className={styles.more}>
              <button
                type="button"
                className={styles.moreRow}
                disabled={list.isFetchingNextPage}
                onClick={() => void list.fetchNextPage()}
              >
                <span>Show {Math.min(PAGE_SIZE, (first?.total ?? 0) - rows.length)} more</span>
                <small>{(first?.total ?? 0) - rows.length} left</small>
              </button>
            </div>
          ) : (
            pages.length > 1 && (
              <p className={styles.end}>
                That is all of {MONTH_NAMES[Number(month.slice(5, 7)) - 1]} · {first?.total} transaction
                {first?.total === 1 ? "" : "s"}
              </p>
            )
          )}
        </>
      ) : (
        first?.upcoming.length === 0 && (
          <EmptyState
            title={searching ? "Nothing matches." : "No transactions yet."}
            action={
              searching ? (
                <Link className={styles.secondary} to="/transactions">
                  Show everything
                </Link>
              ) : (
                <Link className={styles.primary} to="/transactions/new">
                  Record a transaction
                </Link>
              )
            }
          />
        )
      )}

      {filtering && (
        <FilterSheet
          open
          start={chosen}
          filters={filters}
          onClose={() => {
            setFiltering(false);
          }}
          onClear={() => {
            setFiltering(false);
            setParams(new URLSearchParams({ month }));
          }}
          onApply={(picked) => {
            setFiltering(false);
            const changes: Partial<Record<FilterKey, string>> = {};
            for (const key of ["account", "category", "merchant", "tag"] as const)
              changes[key] = picked[key]?.value ?? "";
            setParams(new URLSearchParams(addressWith(changes).split("?")[1]));
          }}
        />
      )}
      {openId && <TransactionSheet key={openId} id={openId} onClose={closeEntry} onOpen={openEntry} />}
    </>
  );
}
