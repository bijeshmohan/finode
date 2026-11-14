// The Filter sheet (transactions.html): Account, Category, Merchant and Tag, each chosen from a list you can search.
// "Show transactions" applies the choices; "Clear all" drops them.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import { Icon } from "../../components/Icon";
import { Sheet } from "../../components/Sheet";
import type { ListFilters } from "./queries";
import styles from "./TransactionsPage.module.css";

export type FilterKey = "account" | "category" | "merchant" | "tag";
export type Chosen = Partial<Record<FilterKey, { value: string; name: string }>>;

interface Choice {
  value: string;
  name: string;
  sub?: string;
}

const ROWS: { key: FilterKey; label: string }[] = [
  { key: "account", label: "Account" },
  { key: "category", label: "Category" },
  { key: "merchant", label: "Merchant" },
  { key: "tag", label: "Tag" },
];

function useChoices(open: boolean): Record<FilterKey, Choice[]> | null {
  const api = useApi();
  const options = useQuery({
    queryKey: ["views", "transaction-filters"],
    queryFn: () => data(api.GET("/api/views/transaction-filters")),
    enabled: open,
  });
  const tags = useQuery({ queryKey: ["tags"], queryFn: () => data(api.GET("/api/tags/")), enabled: open });
  if (!options.data) return null;
  return {
    account: options.data.accounts.map((a) => ({ value: a.id, name: a.name, sub: a.sub })),
    category: options.data.categories.map((c) => ({ value: c.id, name: c.name, sub: c.sub })),
    merchant: options.data.merchants.map((m) => ({ value: m, name: m })),
    tag: (tags.data ?? []).map((t) => ({ value: t.tag, name: `#${t.tag}` })),
  };
}

interface FilterSheetProps {
  open: boolean;
  onClose: () => void;
  start: Chosen;
  onApply: (chosen: Chosen) => void;
  onClear: () => void;
  filters: ListFilters;
}

export function FilterSheet({ open, onClose, start, onApply, onClear, filters }: FilterSheetProps) {
  const choices = useChoices(open);
  const [chosen, setChosen] = useState<Chosen>(start);
  const [picking, setPicking] = useState<FilterKey | null>(null);
  const [search, setSearch] = useState("");
  const anySet = Boolean(filters.account ?? filters.category ?? filters.merchant ?? filters.tag);

  const close = () => {
    setPicking(null);
    onClose();
  };

  if (picking) {
    const label = ROWS.find((r) => r.key === picking)?.label ?? "";
    const wanted = search.trim().toLowerCase();
    const list = (choices?.[picking] ?? []).filter((c) => !wanted || c.name.toLowerCase().includes(wanted));
    return (
      <Sheet open={open} onClose={close} title={label} showTitle={false}>
        <div className={styles.filterHead}>
          <button
            type="button"
            className={styles.linkButton}
            onClick={() => {
              setPicking(null);
            }}
          >
            ‹ Filter
          </button>
          <h2 className={styles.filterTitle}>{label}</h2>
        </div>
        <input
          type="search"
          className={styles.filterSearch}
          placeholder={`Search ${label.toLowerCase()}`}
          aria-label={`Search ${label.toLowerCase()}`}
          autoComplete="off"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
        />
        <ul className={styles.filterOptions}>
          <li>
            <button
              type="button"
              onClick={() => {
                setChosen((now) => Object.fromEntries(Object.entries(now).filter(([key]) => key !== picking)));
                setPicking(null);
              }}
            >
              Any {label.toLowerCase()}
            </button>
          </li>
          {list.map((c) => (
            <li key={c.value}>
              <button
                type="button"
                onClick={() => {
                  setChosen((now) => ({ ...now, [picking]: { value: c.value, name: c.name } }));
                  setPicking(null);
                }}
              >
                <span>
                  {c.name}
                  {c.sub && <small className={styles.muted}>{c.sub}</small>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Sheet>
    );
  }

  return (
    <Sheet open={open} onClose={close} title="Filter">
      {ROWS.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          className={styles.filterRow}
          onClick={() => {
            setSearch("");
            setPicking(key);
          }}
        >
          <span>{label}</span>
          <span className={`${styles.filterCurrent} ${chosen[key] ? styles.set : ""}`.trim()}>
            {chosen[key]?.name ?? "Any"}
          </span>
          <Icon name="caret" />
        </button>
      ))}
      <div className={styles.sheetActions}>
        <button
          type="button"
          className={styles.primary}
          onClick={() => {
            onApply(chosen);
          }}
        >
          Show transactions
        </button>
      </div>
      {anySet && (
        <button type="button" className={styles.filterClear} onClick={onClear}>
          Clear all
        </button>
      )}
    </Sheet>
  );
}
