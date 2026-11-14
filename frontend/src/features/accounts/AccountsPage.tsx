// The Accounts page (accounts.html): net worth, the pinned accounts, then a row of cards per kind (Bank Accounts, Credit
// Cards…, the groups the person made, the plain accounts). Closed accounts wait behind "Load more".
import { useState } from "react";
import { Link } from "react-router";

import { useGrouping } from "../../app/currency";
import { Figure } from "../../components/Figure";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import { formatMoney } from "../../lib/money";
import { AccountCard } from "./AccountCard";
import styles from "./Accounts.module.css";
import { useAccounts } from "./queries";

const plural = (n: number) => `${String(n)} account${n === 1 ? "" : "s"}`;

export function AccountsPage() {
  const grouping = useGrouping();
  const view = useAccounts();
  const [showClosed, setShowClosed] = useState(false);

  if (view.isError) return <LoadError error={view.error} onRetry={() => void view.refetch()} />;
  const page = view.data;
  return (
    <>
      <div className={styles.pageHead}>
        <h1>Accounts</h1>
      </div>
      {page && (
        <>
          <div className={styles.hero}>
            <div className={styles.heroTop}>
              <span>Net worth</span>
            </div>
            <span className={styles.figure}>
              <Figure value={page.net_worth} />
            </span>
            <span className={styles.heroNote}>
              <span>{page.account_count ? plural(page.account_count) : "No accounts yet"}</span>
              {page.has_budget_accounts && (
                <span className={styles.budgetKey}>
                  <i className={styles.dot} />
                  in the budget
                </span>
              )}
            </span>
          </div>

          {page.pinned.length > 0 && (
            <section className={styles.kind}>
              <div className={styles.kindHead}>
                <h2>Pinned</h2>
                <p>{plural(page.pinned.length)}</p>
              </div>
              <div className={styles.rail}>
                {page.pinned.map((c) => (
                  <AccountCard key={c.id} card={c} mark={false} />
                ))}
              </div>
            </section>
          )}
          {page.kinds
            .filter((k) => showClosed || !k.all_closed)
            .map((k) => (
              <section key={k.group_id ?? k.name} className={styles.kind}>
                <div className={styles.kindHead}>
                  <h2>{k.group_id ? <Link to={`/accounts/${k.group_id}`}>{k.name}</Link> : k.name}</h2>
                  <p>
                    {formatMoney(k.total, grouping)}
                    {k.owed ? " owed" : ""} · {plural(k.open_count)}
                  </p>
                </div>
                <div className={styles.rail}>
                  {k.cards
                    .filter((c) => showClosed || !c.closed)
                    .map((c) => (
                      <AccountCard key={c.id} card={c} />
                    ))}
                  <Link className={`${styles.card} ${styles.addCard}`} to={k.add_url}>
                    <Icon name="plus" />
                    Add account
                  </Link>
                </div>
              </section>
            ))}

          {page.has_closed && !showClosed && (
            <p className={styles.toggle}>
              <button
                type="button"
                className={styles.linkButton}
                onClick={() => {
                  setShowClosed(true);
                }}
              >
                Load more
              </button>
            </p>
          )}
          <Link className={styles.addRow} to="/accounts/new-group">
            <Icon name="plus" />
            New group
          </Link>
        </>
      )}
    </>
  );
}
