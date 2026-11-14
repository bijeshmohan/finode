// An account's (or a group's) own page (account.html): its balance and kind, a card's bill, a group's accounts as cards,
// what is dated ahead, and its entries with the running balance, a chunk at a time. The pin and the "…" menu pin, close,
// reopen and edit it.
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { messageOf } from "../../api/messages";
import { useCurrency, useGrouping } from "../../app/currency";
import { useNewEntryHere } from "../../app/newEntry";
import { useToast } from "../../app/toast";
import { Figure } from "../../components/Figure";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import { type HeroOpen, InfoNote, Menu, MenuNote, menuStyles } from "../../components/Menu";
import { formatMoney, withCurrency } from "../../lib/money";
import { sameAmount } from "../../lib/split";
import { RegisterList } from "../transactions/RegisterList";
import { TransactionSheet } from "../transactions/TransactionSheet";
import { UpcomingCard } from "../transactions/UpcomingCard";
import { useOpenEntry } from "../transactions/useOpenEntry";
import { AccountCard } from "./AccountCard";
import styles from "./Accounts.module.css";
import { CardBill } from "./CardBill";
import { type AccountView, useAccount, useAccountAction } from "./queries";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 05 Nov 2026, as the page writes the day an account was closed. */
function longDay(iso: string): string {
  const [year = "", month = "1", day = ""] = iso.split("-");
  return `${day} ${MONTHS[Number(month) - 1] ?? ""} ${year}`;
}

function AccountMenu({
  view,
  open,
  onToggle,
  onError,
}: {
  view: AccountView;
  open: boolean;
  onToggle: (open: boolean) => void;
  onError: (message: string | null) => void;
}) {
  const grouping = useGrouping();
  const code = useCurrency();
  const toast = useToast();
  const navigate = useNavigate();
  const act = useAccountAction();
  const many = view.has_children;
  const it = many ? "them" : "it";
  return (
    <Menu open={open} onToggle={onToggle}>
      <Link to={`/accounts/${view.id}/edit`}>
        <Icon name="edit" />
        Edit
      </Link>
      {view.can_add_child && !view.closed_on && (
        <Link to={`/accounts/new?parent=${view.id}`}>
          <Icon name="plus" />
          {view.is_group ? "Add account" : "Add sub-account"}
        </Link>
      )}
      {view.closed_on ? (
        <>
          <MenuNote>
            Reopen {view.name}
            {many ? " and everything inside it" : ""} to use {it} again.
          </MenuNote>
          <button
            type="button"
            onClick={() => {
              onError(null);
              act.mutate(
                { id: view.id, action: "reopen" },
                {
                  onSuccess: () => {
                    toast("Account reopened");
                    onToggle(false);
                  },
                  onError: (e) => {
                    onError(messageOf(e));
                  },
                },
              );
            }}
          >
            Reopen account
          </button>
        </>
      ) : (
        <>
          <MenuNote>
            Done with {view.name}? Closing {many ? "it and everything inside it" : "it"} removes {it} from your lists
            and pickers. The history stays, and you can reopen {it} any time.
            {!sameAmount(view.balance, "0") &&
              ` It has to be empty first: it still holds ${withCurrency(formatMoney(view.balance, grouping), code)}.`}
          </MenuNote>
          <button
            type="button"
            className={menuStyles.danger}
            onClick={() => {
              if (!window.confirm(`Close ${view.name}? You can reopen it later.`)) return;
              onError(null);
              act.mutate(
                { id: view.id, action: "close" },
                {
                  onSuccess: () => {
                    toast("Account closed");
                    void navigate("/accounts");
                  },
                  onError: (e) => {
                    onToggle(false);
                    onError(messageOf(e));
                  },
                },
              );
            }}
          >
            Close account
          </button>
        </>
      )}
    </Menu>
  );
}

export function AccountPage() {
  const { accountId = "" } = useParams();
  const grouping = useGrouping();
  const code = useCurrency();
  const toast = useToast();
  const pages = useAccount(accountId);
  const act = useAccountAction();
  const [heroOpen, setHeroOpen] = useState<HeroOpen>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, openEntry, closeEntry] = useOpenEntry();
  useNewEntryHere(pages.data?.pages[0]?.new_transaction_url ?? null);

  if (pages.isError) return <LoadError error={pages.error} onRetry={() => void pages.refetch()} />;
  const loaded = pages.data?.pages ?? [];
  const view = loaded[0];
  if (!view) return <h1 className="sr-only">Account</h1>;
  const entries = loaded.flatMap((p) => p.entries);
  const toggle = (which: "menu" | "info") => (open: boolean) => {
    setHeroOpen(open ? which : null);
  };

  return (
    <>
      <Link className={styles.back} to="/accounts">
        <Icon name="back" />
        Accounts
      </Link>
      <header className={styles.accountHero}>
        <div className={styles.title}>
          <div className={styles.names}>
            <div className={styles.nameRow}>
              <h1>
                {view.name}
                {view.badge && <span className={styles.badge}>{view.badge}</span>}
              </h1>
              {view.details && (
                <InfoNote
                  open={heroOpen === "info"}
                  onToggle={toggle("info")}
                  label={`About ${view.name}`}
                  text={view.details}
                />
              )}
            </div>
            <p className={styles.sub}>{view.sub}</p>
          </div>
          <div className={styles.actions}>
            {view.can_pin && (
              <button
                type="button"
                className={styles.pinButton}
                aria-pressed={view.pinned}
                aria-label={view.pinned ? "Unpin" : "Pin to top"}
                title={view.pinned ? "Unpin" : "Pin to top"}
                disabled={act.isPending}
                onClick={() => {
                  act.mutate(
                    { id: view.id, action: view.pinned ? "unpin" : "pin" },
                    {
                      onSuccess: () => {
                        toast(view.pinned ? "Unpinned" : "Pinned");
                      },
                      onError: (e) => {
                        setError(messageOf(e));
                      },
                    },
                  );
                }}
              >
                <Icon name="pin" />
              </button>
            )}
            {view.can_edit && (
              <AccountMenu view={view} open={heroOpen === "menu"} onToggle={toggle("menu")} onError={setError} />
            )}
          </div>
        </div>
        {view.closed_on && (
          <p className={styles.muted}>
            Closed on {longDay(view.closed_on)}. Its history stays; nothing can be added to it until you reopen it.
          </p>
        )}
        <p className={styles.heroBalance}>
          <Figure value={view.balance} />
        </p>
        {view.balance_after !== null && view.upcoming.length > 0 && (
          <p className={styles.balanceAfter}>
            {withCurrency(formatMoney(view.balance_after, grouping), code)} after the {view.upcoming.length} coming up
          </p>
        )}
        {view.direct !== null && !sameAmount(view.direct, "0") && (
          <p className={styles.muted}>
            {formatMoney(view.direct, grouping)} posted directly to {view.name}; the rest is in its sub-accounts.
          </p>
        )}
        <CardBill view={view} />
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
      </header>

      {view.is_group && (
        <>
          <div className={styles.sectionHead}>
            <h2>Accounts</h2>
          </div>
          <div className={styles.rail}>
            {view.cards.map((c) => (
              <AccountCard key={c.id} card={c} />
            ))}
            {view.can_add_child && !view.closed_on && (
              <Link className={`${styles.card} ${styles.addCard}`} to={`/accounts/new?parent=${view.id}`}>
                <Icon name="plus" />
                Add account
              </Link>
            )}
          </div>
        </>
      )}
      <div className={styles.sectionHead}>
        <h2>Transactions</h2>
      </div>
      {view.upcoming.length > 0 && (
        <UpcomingCard items={view.upcoming} total={view.upcoming_total} open={false} onOpen={openEntry} />
      )}
      {entries.length > 0 ? (
        <>
          <RegisterList rows={entries} onOpen={openEntry} />
          {pages.hasNextPage && (
            <div className={styles.more}>
              <button
                type="button"
                className={styles.secondary}
                disabled={pages.isFetchingNextPage}
                onClick={() => void pages.fetchNextPage()}
              >
                Load more
              </button>
            </div>
          )}
        </>
      ) : (
        <div className={styles.empty}>
          <p>No transactions yet.</p>
          {view.new_transaction_url && (
            <Link className={styles.button} to={view.new_transaction_url}>
              Record a transaction
            </Link>
          )}
        </div>
      )}
      {openId && <TransactionSheet id={openId} onClose={closeEntry} onOpen={openEntry} />}
    </>
  );
}
