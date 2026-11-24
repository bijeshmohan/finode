// Coming up: until when, what it comes to and how many payments touch the budget's accounts, then the
// days, soonest first. A rule's row opens the rule; an entry dated ahead opens on its edit screen and comes back here.
// Each row's words and a day's total are the server's (services/coming_up_view.py).
import { Link } from "react-router";

import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { Figure } from "../../components/Figure";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import look from "../../components/Page.module.css";
import { Row } from "../../components/Row";
import { friendlyDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import list from "../transactions/TransactionList.module.css";
import { useComingDays } from "./queries";

export function ComingUpPage() {
  const query = useComingDays();
  const today = useToday();
  const grouping = useGrouping();
  const view = query.data;
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <>
      <Link className={look.back} to="/budget">
        <Icon name="back" />
        Budgets
      </Link>
      <div className={look.pageHead}>
        <h1>Coming up</h1>
      </div>
      {view &&
        (view.days.length > 0 ? (
          <>
            <div className={look.hero}>
              <div className={look.heroTop}>
                <span>Until {friendlyDate(view.through, today)}</span>
              </div>
              {view.total !== null && (
                <span className={look.figure} data-testid="coming-figure">
                  <Figure value={view.total} />
                </span>
              )}
              <span className={look.heroNote}>
                <span>
                  {view.count === 1
                    ? "1 payment that touches your budget accounts"
                    : `${String(view.count)} payments that touch your budget accounts`}
                </span>
              </span>
            </div>
            <div className={list.list}>
              {view.days.map((day) => (
                <section key={day.date}>
                  <h3 className={list.dayHead}>
                    <span>{friendlyDate(day.date, today)}</span>
                    {day.total !== null && <span className={list.dayTotal}>{formatMoney(day.total, grouping)}</span>}
                  </h3>
                  <ul className={list.tile}>
                    {day.rows.map((r, i) => (
                      <li key={`${r.recurring_id ?? r.transaction_id ?? ""}-${String(i)}`}>
                        <Row
                          icon={r.icon}
                          title={r.title}
                          detail={r.sub}
                          extra={
                            r.recurring_id && (
                              <span className={list.via}>
                                <Icon name="repeat" />
                                Repeats
                              </span>
                            )
                          }
                          figure={formatMoney(r.amount, grouping)}
                          figureTone={r.income ? "in" : "plain"}
                          to={
                            r.recurring_id
                              ? `/recurring/${r.recurring_id}/edit`
                              : `/transactions/${r.transaction_id ?? ""}/edit?back=/budget/coming-up`
                          }
                        />
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          </>
        ) : (
          <div className={look.empty}>
            <p>Nothing is coming up before {friendlyDate(view.through, today)}.</p>
          </div>
        ))}
    </>
  );
}
