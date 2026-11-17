// The People list: All · Owe you · You owe (· Archived once someone is), what is owed in all, and a row
// per person with their quiet line and what is owed either way. The words and totals are the server's
// (services/people_view.py).
import { Link, useSearchParams } from "react-router";

import { useGrouping } from "../../app/currency";
import { Chips } from "../../components/Chips";
import { Figure } from "../../components/Figure";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import look from "../../components/Page.module.css";
import rows from "../../components/Rows.module.css";
import { formatMoney } from "../../lib/money";
import { positive, sameAmount } from "../../lib/split";
import styles from "./People.module.css";
import { type PeopleView, type Show, usePeople } from "./queries";

const SHOWS: readonly Show[] = ["all", "owed", "owe", "archived"];
const isShow = (value: string | null): value is Show => value !== null && (SHOWS as readonly string[]).includes(value);

/** What a person's net reads at the right: owed to you in green, what you owe in red, nothing as a dash. */
export function Owed({ net }: { net: string }) {
  const grouping = useGrouping();
  if (sameAmount(net, "0")) return <span className={rows.dash}>–</span>;
  if (positive(net)) return <span className={rows.income}>{formatMoney(net, grouping)}</span>;
  return <span className={styles.out}>{formatMoney(net.replace("-", ""), grouping)}</span>;
}

function Head({ view }: { view: PeopleView }) {
  const grouping = useGrouping();
  const owed = !sameAmount(view.owed_total, "0");
  const owe = !sameAmount(view.owe_total, "0");
  return (
    <div className={look.hero} data-testid="people-head">
      <div className={look.heroTop}>
        <span>{view.label}</span>
      </div>
      {(owed || owe) && (
        <>
          <span className={look.figure} data-testid="people-figure">
            <Figure value={view.difference} />
          </span>
          <span className={look.heroNote}>
            <span>
              {owed && owe
                ? `${formatMoney(view.owed_total, grouping)} owed to you · ${formatMoney(view.owe_total, grouping)} you owe`
                : "in total"}
            </span>
          </span>
        </>
      )}
    </div>
  );
}

export function PeoplePage() {
  const [params, setParams] = useSearchParams();
  const asked = params.get("show");
  const show: Show = isShow(asked) ? asked : "all";
  const query = usePeople(show);
  const view = query.data;
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <>
      <Link className={look.back} to="/settings">
        <Icon name="back" />
        Settings
      </Link>
      <div className={look.pageHead}>
        <h1>People</h1>
      </div>
      {view && (
        <>
          {(view.everyone || view.show === "archived") && (
            <>
              <div className={rows.catBar}>
                <Chips
                  label="Show"
                  options={[
                    ...view.shows.map((s) => ({ value: s.key as Show, label: s.name })),
                    ...(view.has_archived ? [{ value: "archived" as Show, label: "Archived" }] : []),
                  ]}
                  value={view.show}
                  onChange={(next) => {
                    setParams(next === "all" ? new URLSearchParams() : new URLSearchParams({ show: next }));
                  }}
                />
              </div>
              <Head view={view} />
            </>
          )}
          {view.rows.length > 0 ? (
            <div className={rows.tile}>
              {view.rows.map((r) => (
                <Link key={r.id} className={rows.row} to={`/people/${r.id}`}>
                  <span className={rows.main}>
                    <span className={rows.name}>{r.name}</span>
                    <span className={rows.rowSub}>{r.sub}</span>
                  </span>
                  <span className={rows.amount}>
                    <Owed net={r.net} />
                  </span>
                </Link>
              ))}
            </div>
          ) : view.everyone ? (
            <div className={look.empty}>
              <p>Nobody here.</p>
            </div>
          ) : (
            view.show !== "archived" && (
              <div className={look.empty}>
                <p>Keep track of money you lend, borrow and share with people.</p>
                <Link className={look.button} to="/people/new">
                  Add a person
                </Link>
              </div>
            )
          )}
          {view.everyone && view.show !== "archived" && (
            <Link className={look.addRow} to="/people/new">
              <Icon name="plus" />
              Add person
            </Link>
          )}
        </>
      )}
    </>
  );
}
