// The Accounts page: the pinned accounts, then a list per type (Bank Account, Cash, Credit Card, Prepaid Wallet, in
// the person's order), each under its heading with its total. Every account is part of the budget. Closed accounts wait
// behind "Load more". Nothing scrolls sideways (the owner's choice, 2026-11-24).
import { useState } from "react";

import { useGrouping } from "../../app/currency";
import { CategoryIcon } from "../../components/CategoryIcon";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import { formatMoney } from "../../lib/money";
import { AccountRows } from "./AccountRows";
import look from "../../components/Page.module.css";
import styles from "./Accounts.module.css";
import { useAccounts } from "./queries";

const plural = (n: number) => `${String(n)} account${n === 1 ? "" : "s"}`;

/** The line that ends each type's list. */
const ADD: Record<string, string> = {
  "assets.bank": "Add bank account",
  "assets.cash": "Add cash account",
  "liabilities.cards": "Add credit card",
  "assets.wallet": "Add prepaid wallet",
};

export function AccountsPage() {
  const grouping = useGrouping();
  const view = useAccounts();
  const [showClosed, setShowClosed] = useState(false);

  if (view.isError) return <LoadError error={view.error} onRetry={() => void view.refetch()} />;
  const page = view.data;
  return (
    <>
      <div className={look.pageHead}>
        <h1>Accounts</h1>
      </div>
      {page && (
        <>
          <p className={look.sub}>{page.account_count ? plural(page.account_count) : "No accounts yet"}</p>

          {page.pinned.length > 0 && (
            <section className={styles.kind}>
              <div className={styles.kindHead}>
                <div>
                  <div className={styles.kindTitle}>
                    <span className={styles.typeIcon}>
                      <Icon name="pin" />
                    </span>
                    <h2>Pinned</h2>
                  </div>
                  <p>{plural(page.pinned.length)}</p>
                </div>
              </div>
              <AccountRows cards={page.pinned} withIcons />
            </section>
          )}
          {page.kinds
            .filter((k) => showClosed || !k.all_closed)
            .map((k) => (
              <section key={k.type} className={styles.kind}>
                <div className={styles.kindHead}>
                  <div>
                    <div className={styles.kindTitle}>
                      <span className={styles.typeIcon}>
                        <CategoryIcon name={k.icon} />
                      </span>
                      <h2>{k.name}</h2>
                    </div>
                    <p>{plural(k.open_count)}</p>
                  </div>
                  <p className={styles.kindTotal}>
                    <span>{formatMoney(k.total, grouping)}</span>
                    {k.owed && <small>owed</small>}
                  </p>
                </div>
                <AccountRows
                  cards={k.cards.filter((c) => showClosed || !c.closed)}
                  add={{ to: k.add_url, label: ADD[k.type] ?? "Add account" }}
                />
              </section>
            ))}

          {page.has_closed && !showClosed && (
            <p className={look.toggle}>
              <button
                type="button"
                className={look.linkButton}
                onClick={() => {
                  setShowClosed(true);
                }}
              >
                Load more
              </button>
            </p>
          )}
        </>
      )}
    </>
  );
}
