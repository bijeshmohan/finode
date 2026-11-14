// Relating an entry to an earlier one (a refund, a reversal): the Related button, the sheet that finds the earlier
// entry, and the chip that names it with ✕ to remove the link.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { data } from "../../api/client";
import { useApi } from "../../api/context";
import { useGrouping } from "../../app/currency";
import { Icon } from "../../components/Icon";
import { Sheet } from "../../components/Sheet";
import { formatMoney } from "../../lib/money";
import type { Row } from "../transactions/queries";
import styles from "./EntryScreen.module.css";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function dayMonth(iso: string): string {
  const [, month = "1", day = "1"] = iso.split("-");
  return `${day.padStart(2, "0")} ${MONTHS[Number(month) - 1] ?? ""}`;
}

interface RelatedProps {
  value: Row | null;
  onChange: (row: Row | null) => void;
  /** The entry being edited: never related to itself. */
  exclude?: string | undefined;
}

export function Related({ value, onChange, exclude }: RelatedProps) {
  const grouping = useGrouping();
  const [open, setOpen] = useState(false);
  if (value) {
    return (
      <div className={styles.chipNote}>
        <span>
          <small>Related to</small>
          <b>
            {value.title} · {dayMonth(value.date)} · {formatMoney(value.amount, grouping)}
          </b>
        </span>
        <button
          type="button"
          className={styles.linkButton}
          aria-label="Remove the link"
          onClick={() => {
            onChange(null);
          }}
        >
          ✕
        </button>
      </div>
    );
  }
  return (
    <>
      <button
        type="button"
        className={styles.metaChip}
        onClick={() => {
          setOpen(true);
        }}
      >
        <Icon name="link" />
        Related
      </button>
      {open && (
        <RelatedSheet
          exclude={exclude}
          onClose={() => {
            setOpen(false);
          }}
          onPick={(row) => {
            onChange(row);
            setOpen(false);
          }}
        />
      )}
    </>
  );
}

function RelatedSheet({
  exclude,
  onClose,
  onPick,
}: {
  exclude?: string | undefined;
  onClose: () => void;
  onPick: (row: Row) => void;
}) {
  const api = useApi();
  const grouping = useGrouping();
  const [q, setQ] = useState("");
  const found = useQuery({
    queryKey: ["related-entries", q.trim(), exclude ?? ""],
    queryFn: () =>
      data(
        api.GET("/api/views/related-entries", {
          params: { query: { q: q.trim(), ...(exclude ? { exclude } : {}) } },
        }),
      ),
  });
  return (
    <Sheet open onClose={onClose} title="Related to…">
      <input
        type="search"
        className={styles.search}
        placeholder="Search payee, note or account"
        aria-label="Search transactions"
        autoComplete="off"
        value={q}
        onChange={(event) => {
          setQ(event.target.value);
        }}
      />
      <ul className={styles.options}>
        {found.data?.length === 0 && (
          <li className={styles.muted}>{q.trim() ? "Nothing matches." : "No earlier transactions."}</li>
        )}
        {found.data?.map((row) => (
          <li key={row.id}>
            <button
              type="button"
              onClick={() => {
                onPick(row);
              }}
            >
              <span>
                {row.title}
                <small className={styles.muted}>
                  {dayMonth(row.date)} {row.date.slice(0, 4)} · {row.sub}
                </small>
              </span>
              <span className={row.kind === "income" ? styles.income : undefined}>
                {row.kind === "income" ? "+" : ""}
                {formatMoney(row.amount, grouping)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}
