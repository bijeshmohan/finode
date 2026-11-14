// A category's own page (category.html): its month (the month pill beside the way back), its subcategories with theirs
// and "Everything else" labelled with it itself, and its own entries. The menu edits, adds a subcategory, deletes or
// restores it.
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { messageOf } from "../../api/messages";
import { useGrouping } from "../../app/currency";
import { useNewEntryHere } from "../../app/newEntry";
import { useToday } from "../../app/session";
import { useToast } from "../../app/toast";
import { Figure } from "../../components/Figure";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import { type HeroOpen, InfoNote, Menu, MenuNote, menuStyles } from "../../components/Menu";
import { MonthPill } from "../../components/MonthPill";
import look from "../../components/Page.module.css";
import { formatMoney } from "../../lib/money";
import { positive, sameAmount } from "../../lib/split";
import { RegisterList } from "../transactions/RegisterList";
import { TransactionSheet } from "../transactions/TransactionSheet";
import { useOpenEntry } from "../transactions/useOpenEntry";
import styles from "./Categories.module.css";
import { monthName } from "./CategoriesPage";
import { type CategoryView, useCategory, useCategoryChange } from "./queries";

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
  const subs = view.subs.length > 0;
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
      {view.can_add_child && (
        <Link to={`/categories/new?parent=${view.id}`}>
          <Icon name="plus" />
          Add subcategory
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
                `Delete ${view.name}${subs ? " and the subcategories in it" : ""}? If there are entries, they stay in ` +
                `your history and reports, but ${subs ? "these categories leave" : "it leaves"} your lists and pickers.`;
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
  const grouping = useGrouping();
  const [params, setParams] = useSearchParams();
  const asked = params.get("month");
  const query = useCategory(categoryId, asked);
  const [heroOpen, setHeroOpen] = useState<HeroOpen>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, openEntry, closeEntry] = useOpenEntry();
  const view = query.data;
  useNewEntryHere(view?.new_transaction_url ?? null);

  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  if (!view) return <h1 className="sr-only">Category</h1>;
  const earning = view.kind === "earning";
  const tab = earning ? "income" : "expense";
  const money = (value: string) => (
    <span className={earning && positive(value) ? styles.income : undefined}>{formatMoney(value, grouping)}</span>
  );
  const toggle = (which: "menu" | "info") => (open: boolean) => {
    setHeroOpen(open ? which : null);
  };
  const hasOwn = !sameAmount(view.own_here, "0");

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
            <p className={look.sub}>{view.group ? view.group.name : earning ? "Earning" : "Spending"}</p>
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
        <p className={look.heroBalance}>
          <Figure value={view.total} />
        </p>
        {error && (
          <p className={look.error} role="alert">
            {error}
          </p>
        )}
      </header>

      {(view.subs.length > 0 || hasOwn) && (
        <>
          <div className={look.sectionHead}>
            <h2>Subcategories</h2>
          </div>
          <div className={styles.tile}>
            {view.subs.map((s) => (
              <Link key={s.id} className={styles.row} to={`/categories/${s.id}?month=${view.month}`}>
                <span className={styles.main}>
                  <span className={styles.name}>{s.name}</span>
                </span>
                <span className={styles.amount}>{money(s.total)}</span>
              </Link>
            ))}
            {hasOwn && (
              <div className={styles.row}>
                <span className={styles.main}>
                  <span className={styles.name}>Everything else</span>
                  <span className={styles.rowSub}>posted to {view.name} itself</span>
                </span>
                <span className={styles.amount}>{money(view.own_here)}</span>
              </div>
            )}
          </div>
          {view.can_add_child && (
            <Link className={look.addRow} to={`/categories/new?parent=${view.id}`}>
              <Icon name="plus" />
              Add subcategory
            </Link>
          )}
        </>
      )}

      {(view.entries.length > 0 || view.subs.length === 0) && (
        <div className={look.sectionHead}>
          <h2>Transactions</h2>
        </div>
      )}
      {view.entries.length > 0 ? (
        <RegisterList rows={view.entries} onOpen={openEntry} />
      ) : (
        view.subs.length === 0 && (
          <div className={look.empty}>
            <p>Nothing in {monthName(view.month)}.</p>
          </div>
        )
      )}
      {openId && <TransactionSheet id={openId} onClose={closeEntry} onOpen={openEntry} />}
    </>
  );
}
