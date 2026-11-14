// One transaction's details, in the sheet over a list (partials/txn_sheet.html): what it was, from and to, the note and
// tags, then everything else behind one "More" row so Edit stays clear of a thumb opening it. Delete asks first and is
// for good.
import { useEffect } from "react";
import { Link } from "react-router";

import { messageOf } from "../../api/messages";
import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { Icon } from "../../components/Icon";
import { Sheet } from "../../components/Sheet";
import { friendlyDate, shortDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { type Details, type Row, useDeleteTransaction, useTransactionDetails } from "./queries";
import styles from "./TransactionSheet.module.css";

const ASK = "Delete this transaction? Account balances will change. This cannot be undone.";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 13 Nov 2026: the full date, after "Today" or "Yesterday". */
function fullDate(iso: string): string {
  const [year = "", month = "1", day = "1"] = iso.split("-");
  return `${day.padStart(2, "0")} ${MONTHS[Number(month) - 1] ?? ""} ${year}`;
}

interface SheetProps {
  id: string;
  onClose: () => void;
  /** Open another entry's details (a related one) in the same sheet. */
  onOpen: (id: string) => void;
}

export function TransactionSheet({ id, onClose, onOpen }: SheetProps) {
  const details = useTransactionDetails(id);
  const failed = details.isError;
  useEffect(() => {
    if (failed) onClose();
  }, [failed, onClose]);

  return (
    <Sheet open onClose={onClose} title="Transaction details" showTitle={false} panelOnWide>
      {details.data ? (
        <Content details={details.data} onClose={onClose} onOpen={onOpen} />
      ) : (
        <div className={styles.placeholder} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      )}
    </Sheet>
  );
}

function Lines({ lines, today }: { lines: Details["from_lines"]; today: string }) {
  const grouping = useGrouping();
  return (
    <>
      {lines.map((line, i) => (
        <span key={`${line.name}-${String(i)}`}>
          {line.name}
          {lines.length > 1 && <small className={styles.muted}> {formatMoney(line.amount, grouping)}</small>}
          {line.posted_on && <small className={styles.muted}> posts {shortDate(line.posted_on, today)}</small>}
        </span>
      ))}
    </>
  );
}

function RelatedRow({ row, today, onOpen }: { row: Row; today: string; onOpen: (id: string) => void }) {
  const grouping = useGrouping();
  return (
    <button
      type="button"
      className={styles.relatedRow}
      onClick={() => {
        onOpen(row.id);
      }}
    >
      <span>
        {row.title}
        <small className={styles.muted}>{friendlyDate(row.date, today)}</small>
      </span>
      <span className={row.kind === "income" ? styles.income : undefined}>
        {row.kind === "income" ? "+" : ""}
        {formatMoney(row.amount, grouping)}
      </span>
    </button>
  );
}

function Content({
  details: d,
  onClose,
  onOpen,
}: {
  details: Details;
  onClose: () => void;
  onOpen: (id: string) => void;
}) {
  const today = useToday();
  const grouping = useGrouping();
  const remove = useDeleteTransaction();
  const { row } = d;
  const when = friendlyDate(row.date, today);
  const related = d.related_to ? [d.related_to] : d.related;
  const byAgent = d.added_by ?? d.changed_by;
  const hasMore = related.length > 0 || Boolean(d.source) || Boolean(byAgent) || row.recurring;
  const month = row.date.slice(0, 7);

  return (
    <>
      <div className={styles.title}>
        <div>
          <h2>{row.title}</h2>
          <p className={styles.muted}>
            {when === "Today" || when === "Yesterday" ? `${when} · ${fullDate(row.date)}` : when}
          </p>
        </div>
        <div className={`${styles.amount} ${row.kind === "income" ? styles.income : ""}`.trim()}>
          {row.kind === "income" ? "+" : ""}
          {formatMoney(row.amount, grouping)}
        </div>
      </div>

      <dl className={styles.facts}>
        <div>
          <dt>{d.from_label}</dt>
          <dd>
            <Lines lines={d.from_lines} today={today} />
          </dd>
        </div>
        <div>
          <dt>{d.to_label}</dt>
          <dd>
            <Lines lines={d.to_lines} today={today} />
          </dd>
        </div>
        {d.comment && (
          <div>
            <dt>Note</dt>
            <dd>{d.comment}</dd>
          </div>
        )}
        {d.tags.length > 0 && (
          <div>
            <dt>Tags</dt>
            <dd className={styles.tags}>
              {d.tags.map((tag) => (
                <Link key={tag} to={`/transactions?month=${month}&tag=${encodeURIComponent(tag)}`}>
                  #{tag}
                </Link>
              ))}
            </dd>
          </div>
        )}
      </dl>

      {hasMore && (
        <details className={styles.extra}>
          <summary>
            <span>More</span>
            <Icon name="chevron-right" />
          </summary>
          {related.length > 0 && (
            <div className={styles.related}>
              <p className={styles.relatedHead}>
                {d.related_to ? "Related to" : `Related · ${String(related.length)}`}
              </p>
              {related.map((r) => (
                <RelatedRow key={r.id} row={r} today={today} onOpen={onOpen} />
              ))}
            </div>
          )}
          {byAgent ? (
            <p className={styles.by}>
              <Icon name="robot" />
              <span>
                {d.added_by && `Added by ${d.added_by}`}
                {d.changed_by && `${d.added_by ? " · " : ""}last changed by ${d.changed_by}`}
              </span>
            </p>
          ) : (
            row.recurring && (
              <p className={styles.by}>
                <Icon name="repeat" />
                <Link to="/recurring">Recurring</Link>
              </p>
            )
          )}
          {d.source && (
            <dl className={styles.facts}>
              <div>
                <dt>Source</dt>
                <dd>
                  {d.source_url ? (
                    <a href={d.source_url} target="_blank" rel="noopener noreferrer">
                      {d.source}
                    </a>
                  ) : (
                    d.source
                  )}
                  {d.external_id && <small className={styles.muted}> {d.external_id}</small>}
                </dd>
              </div>
            </dl>
          )}
        </details>
      )}

      {remove.isError && (
        <p className={styles.error} role="alert">
          {messageOf(remove.error)}
        </p>
      )}
      {d.person && !d.loan_like ? (
        <>
          <p className={styles.hint}>
            This is part of what you did with {d.person.name}. Change or reverse it from their page.
          </p>
          <div className={styles.actions}>
            <Link className={styles.button} to={`/people/${d.person.id}`}>
              Open {d.person.name}
            </Link>
          </div>
        </>
      ) : (
        <>
          <div className={styles.actions}>
            <Link className={styles.button} to={`/transactions/${row.id}/edit`}>
              Edit
            </Link>
          </div>
          {d.person ? (
            <p className={styles.hint}>
              This is part of what you did with {d.with_names.join(", ")}. What has been paid back is on{" "}
              <Link to={`/people/${d.person.id}`}>
                {d.with_names.length === 1 ? "their page" : `${d.person.name}'s page`}
              </Link>
              .
            </p>
          ) : (
            <div className={styles.links}>
              <Link to={`/transactions/new?repeat=${row.id}`}>Repeat</Link>
              <Link to={`/transactions/new?related=${row.id}`}>Related</Link>
              <button
                type="button"
                className={styles.delete}
                disabled={remove.isPending}
                onClick={() => {
                  if (!window.confirm(ASK)) return;
                  remove.mutate(row.id, { onSuccess: onClose });
                }}
              >
                Delete
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}
