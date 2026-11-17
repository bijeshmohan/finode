// The Recurring list: the rules on repeat, then under Paused the paused and ended ones. Each row's
// status and schedule are the server's (services/recurring_view.py); a row opens the rule.
import { Link } from "react-router";

import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import look from "../../components/Page.module.css";
import { Row } from "../../components/Row";
import { shortDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import list from "../transactions/TransactionList.module.css";
import { type RuleRow, useRecurringList } from "./queries";
import styles from "./Recurring.module.css";

function Rules({ rows, heading }: { rows: RuleRow[]; heading?: string }) {
  const grouping = useGrouping();
  const today = useToday();
  const said = (r: RuleRow) => {
    if (r.status === "error") return <span className={styles.failing}>Couldn&apos;t record: {r.last_error}</span>;
    if (r.status === "paused") return `${r.schedule} · paused`;
    if (r.status === "ended") return `${r.schedule} · ended`;
    return `${r.schedule} · next ${shortDate(r.next_date, today)}`;
  };
  return (
    <section>
      {heading && (
        <h3 className={list.dayHead}>
          <span>{heading}</span>
        </h3>
      )}
      <ul className={list.tile}>
        {rows.map((r) => {
          const stopped = r.status === "paused" || r.status === "ended";
          return (
            <li key={r.id} className={stopped ? styles.quiet : undefined}>
              <Row
                title={r.title}
                detail={said(r)}
                figure={formatMoney(r.amount, grouping)}
                to={`/recurring/${r.id}/edit`}
              />
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function RecurringPage() {
  const query = useRecurringList();
  const view = query.data;
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <>
      <Link className={look.back} to="/settings">
        <Icon name="back" />
        Settings
      </Link>
      <div className={look.pageHead}>
        <h1>Recurring</h1>
      </div>
      {view && (
        <div className={list.list}>
          {view.live.length > 0 && <Rules rows={view.live} />}
          {view.stopped.length > 0 && <Rules rows={view.stopped} heading="Paused" />}
          {view.live.length === 0 && view.stopped.length === 0 && (
            <div className={look.empty}>
              <p>Nothing on repeat yet. Rent, salary, subscriptions: set once, recorded on schedule.</p>
            </div>
          )}
        </div>
      )}
      <Link className={look.addRow} to="/recurring/new">
        <Icon name="plus" />
        New recurring
      </Link>
    </>
  );
}
