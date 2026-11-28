// A category's own page: its month (the month pill beside the way back) and its entries. The menu edits, deletes or
// restores it.
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { messageOf } from "../../api/messages";
import { useNewEntryHere } from "../../app/newEntry";
import { useToday } from "../../app/session";
import { useToast } from "../../app/toast";
import { CategoryIcon } from "../../components/CategoryIcon";
import { Figure } from "../../components/Figure";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import { type HeroOpen, InfoNote, Menu, MenuNote, menuStyles } from "../../components/Menu";
import { MonthPill } from "../../components/MonthPill";
import look from "../../components/Page.module.css";
import { monthName } from "../../lib/dates";
import { RegisterList } from "../transactions/RegisterList";
import { TransactionSheet } from "../transactions/TransactionSheet";
import { useOpenEntry } from "../transactions/useOpenEntry";
import styles from "../../components/Rows.module.css";
import { type CategoryView, useCategory, useCategoryChange } from "./queries";
import { useTabTitle } from "../../app/title";

const SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function longDay(iso: string): string {
  const [year = "", month = "1", day = ""] = iso.split("-");
  return `${day} ${SHORT[Number(month) - 1] ?? ""} ${year}`;
}

function CategoryMenu({
  view,
  open,
  onToggle,
  onError,
}: {
  view: CategoryView;
  open: boolean;
  onToggle: (open: boolean) => void;
  onError: (message: string | null) => void;
}) {
  const change = useCategoryChange();
  const toast = useToast();
  const navigate = useNavigate();
  const earning = view.kind === "earning";
  return (
    <Menu open={open} onToggle={onToggle}>
      <Link to={`/categories/${view.id}/edit`}>
        <Icon name="edit" />
        Edit
      </Link>
      {!earning && (
        <Link to="/budget">
          <Icon name="budget" />
          See in Budgets
        </Link>
      )}
      {view.closed_on ? (
        <>
          <MenuNote>
            {view.name} was deleted: it is out of your lists and pickers, and its history stays in the reports.
          </MenuNote>
          <button
            type="button"
            onClick={() => {
              onError(null);
              change.mutate(
                { action: "reopen", id: view.id },
                {
                  onSuccess: () => {
                    toast("Category restored");
                    onToggle(false);
                  },
                  onError: (e) => {
                    onError(messageOf(e));
                  },
                },
              );
            }}
          >
            Restore category
          </button>
        </>
      ) : (
        !view.built_in && (
          <button
            type="button"
            className={menuStyles.danger}
            onClick={() => {
              const ask =
                `Delete ${view.name}? If there are entries, they stay in your history and reports, but it leaves ` +
                "your lists and pickers.";
              if (!window.confirm(ask)) return;
              onError(null);
              change.mutate(
                { action: "delete", id: view.id },
                {
                  onSuccess: () => {
                    toast("Category deleted");
                    void navigate(earning ? "/categories?tab=income" : "/categories");
                  },
                  onError: (e) => {
                    onToggle(false);
                    onError(messageOf(e));
                  },
                },
              );
            }}
          >
            <Icon name="trash" />
            Delete category
          </button>
        )
      )}
    </Menu>
  );
}

export function CategoryPage() {
  const { categoryId = "" } = useParams();
  const today = useToday();
  const [params, setParams] = useSearchParams();
  const asked = params.get("month");
  const query = useCategory(categoryId, asked);
  const [heroOpen, setHeroOpen] = useState<HeroOpen>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, openEntry, closeEntry] = useOpenEntry();
  const view = query.data;
  useNewEntryHere(view?.new_transaction_url ?? null);
  useTabTitle(view?.name);

  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  if (!view) return <h1 className="sr-only">Category</h1>;
  const earning = view.kind === "earning";
  const tab = earning ? "income" : "expense";
  const toggle = (which: "menu" | "info") => (open: boolean) => {
    setHeroOpen(open ? which : null);
  };

  return (
    <>
      <div className={styles.nav}>
        <Link className={look.back} to={`/categories?month=${view.month}&tab=${tab}`}>
          <Icon name="back" />
          Categories
        </Link>
        <MonthPill
          month={view.month}
          max={today.slice(0, 7)}
          onChange={(m) => {
            setParams(new URLSearchParams({ month: m }));
          }}
        />
      </div>
      <header className={look.accountHero}>
        <div className={look.title}>
          <div className={look.names}>
            <div className={look.nameRow}>
              <span className={styles.icon}>
                <CategoryIcon name={view.icon} />
              </span>
              <h1>
                {view.name}
                {view.built_in && <span className={look.badge}>built in</span>}
                {view.closed_on && <span className={look.badge}>closed</span>}
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
            <p className={look.sub}>{earning ? "Earning" : "Spending"}</p>
          </div>
          <div className={look.actions}>
            <CategoryMenu view={view} open={heroOpen === "menu"} onToggle={toggle("menu")} onError={setError} />
          </div>
        </div>
        {view.closed_on && (
          <p className={look.muted}>
            Closed on {longDay(view.closed_on)}. Its history stays; nothing can be added to it until you restore it.
          </p>
        )}
        <div className={look.heroCard}>
          <p className={look.heroBalance}>
            <Figure value={view.total} />
          </p>
        </div>
        {error && (
          <p className={look.error} role="alert">
            {error}
          </p>
        )}
      </header>

      <div className={look.sectionHead}>
        <h2>Transactions</h2>
      </div>
      {view.entries.length > 0 ? (
        <RegisterList rows={view.entries} onOpen={openEntry} />
      ) : (
        <div className={look.empty}>
          <p>Nothing in {monthName(view.month)}.</p>
        </div>
      )}
      {openId && <TransactionSheet id={openId} onClose={closeEntry} onOpen={openEntry} />}
    </>
  );
}
