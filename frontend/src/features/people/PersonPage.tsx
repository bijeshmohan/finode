// A person's page (person.html): what they owe you or you owe them, the short-hands to the Add screen, what is open and
// what was done with them (each opening its sheet), and the menu. Who owes whom and how each row reads are the
// server's (services/people_view.py).
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { messageOf } from "../../api/messages";
import { useGrouping } from "../../app/currency";
import { useToday } from "../../app/session";
import { useToast } from "../../app/toast";
import { Figure } from "../../components/Figure";
import { Icon } from "../../components/Icon";
import { LoadError } from "../../components/LoadError";
import { type HeroOpen, Menu, MenuNote, menuStyles } from "../../components/Menu";
import look from "../../components/Page.module.css";
import rows from "../../components/Rows.module.css";
import { friendlyDate } from "../../lib/dates";
import { formatMoney } from "../../lib/money";
import { positive, sameAmount } from "../../lib/split";
import { EntrySheet } from "./EntrySheet";
import styles from "./People.module.css";
import { type PersonAction, type PersonView, usePerson, usePersonAction } from "./queries";

const SAID = {
  archived: "Person archived. Their history stays.",
  deleted: "Person removed",
  restored: "Person restored",
} as const;

function PersonMenu({ view, onError }: { view: PersonView; onError: (message: string | null) => void }) {
  const [open, setOpen] = useState<HeroOpen>(null);
  const act = usePersonAction(view.id);
  const toast = useToast();
  const navigate = useNavigate();
  const run = (action: PersonAction) => {
    onError(null);
    act.mutate(action, {
      onSuccess: (outcome) => {
        toast(SAID[outcome]);
        setOpen(null);
        if (outcome !== "restored") void navigate("/people");
      },
      onError: (e) => {
        setOpen(null);
        onError(messageOf(e));
      },
    });
  };
  const owes = !sameAmount(view.receivable, "0") || !sameAmount(view.payable, "0");
  return (
    <Menu
      open={open === "menu"}
      onToggle={(next) => {
        setOpen(next ? "menu" : null);
      }}
    >
      <Link to={`/people/${view.id}/edit`}>
        <Icon name="edit" />
        Edit
      </Link>
      {!view.archived && (
        <Link to={`/people/${view.id}/opening`}>
          <Icon name="plus" />
          Add an opening balance
        </Link>
      )}
      {view.archived ? (
        <button
          type="button"
          onClick={() => {
            run("restore");
          }}
        >
          Restore {view.name}
        </button>
      ) : (
        !owes && (
          <>
            <MenuNote>Archiving hides {view.name} from new entries. What you did together stays.</MenuNote>
            <button
              type="button"
              onClick={() => {
                run("archive");
              }}
            >
              Archive
            </button>
          </>
        )
      )}
      <button
        type="button"
        className={menuStyles.danger}
        onClick={() => {
          const ask = `Remove ${view.name}? Someone you never dealt with is deleted; otherwise they are archived.`;
          if (!window.confirm(ask)) return;
          run("remove");
        }}
      >
        <Icon name="trash" />
        Remove
      </button>
    </Menu>
  );
}

export function PersonPage() {
  const { contactId = "" } = useParams();
  const query = usePerson(contactId);
  const today = useToday();
  const grouping = useGrouping();
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<{ id: string; title: string } | null>(null);
  const view = query.data;
  if (query.isError) return <LoadError error={query.error} onRetry={() => void query.refetch()} />;
  if (!view) return <h1 className="sr-only">Person</h1>;
  const money = (value: string) => formatMoney(value, grouping);
  const settled = sameAmount(view.net, "0");
  const owesYou = positive(view.net);
  const go = `&back=/people/${view.id}`;
  const owes = !sameAmount(view.receivable, "0") || !sameAmount(view.payable, "0");
  const details = [view.phone, view.email].filter(Boolean).join(" · ");

  return (
    <>
      <Link className={look.back} to="/people">
        <Icon name="back" />
        People
      </Link>
      <header className={look.accountHero}>
        <div className={look.title}>
          <div className={look.names}>
            <div className={look.nameRow}>
              <h1>
                {view.name}
                {view.archived && <span className={look.badge}>archived</span>}
              </h1>
            </div>
            {details && <p className={look.sub}>{details}</p>}
          </div>
          <div className={look.actions}>
            <PersonMenu view={view} onError={setError} />
          </div>
        </div>
        {error && (
          <p className={look.error} role="alert">
            {error}
          </p>
        )}
        <p className={look.muted}>
          {settled ? "All settled up" : owesYou ? `${view.name} owes you` : `You owe ${view.name}`}
        </p>
        <p className={look.heroBalance} data-testid="person-figure">
          <Figure value={view.net.replace("-", "")} />
        </p>
      </header>

      {!view.archived && (
        <div className={styles.shortHands}>
          <Link to={`/transactions/new?mode=split&with=${view.id}${go}`}>Expense</Link>
          <Link to={`/transactions/new?move=lend&with=${view.id}${go}`}>Lend</Link>
          <Link to={`/transactions/new?move=borrow&with=${view.id}${go}`}>Borrow</Link>
          {owes && <Link to={`/transactions/new?move=settle&with=${view.id}${go}`}>Settle</Link>}
        </div>
      )}

      {view.open.length > 0 && (
        <>
          <div className={look.sectionHead}>
            <h2>Open</h2>
          </div>
          <div className={rows.tile}>
            {view.open.map((o) => (
              <button
                key={o.transaction_id}
                type="button"
                className={`${rows.row} ${styles.rowButton}`}
                onClick={() => {
                  setOpened({ id: o.transaction_id, title: o.name });
                }}
              >
                <span className={rows.main}>
                  <span className={rows.name}>{o.name}</span>
                  <span className={rows.rowSub}>
                    {friendlyDate(o.date, today)}
                    {o.who && ` · ${o.who}`}
                    {o.settled !== null && ` · ${money(o.settled)} of ${money(o.original)} paid`}
                  </span>
                </span>
                <span className={rows.amount}>
                  <span className={o.receivable ? rows.income : styles.out}>{money(o.outstanding)}</span>
                </span>
              </button>
            ))}
          </div>
        </>
      )}

      <div className={look.sectionHead}>
        <h2>Activity</h2>
      </div>
      {view.activity.length > 0 ? (
        <>
          <div className={rows.tile}>
            {view.activity.map((a) => (
              <button
                key={a.transaction_id}
                type="button"
                className={`${rows.row} ${styles.rowButton}`}
                onClick={() => {
                  setOpened({ id: a.transaction_id, title: a.title });
                }}
              >
                <span className={rows.main}>
                  <span className={rows.name}>{a.title}</span>
                  <span className={rows.rowSub}>
                    {friendlyDate(a.date, today)}
                    {a.sub && ` · ${a.sub}`}
                  </span>
                </span>
                <span className={rows.amount}>
                  <span className={a.income ? rows.income : undefined}>{money(a.amount)}</span>
                </span>
              </button>
            ))}
          </div>
          {view.more_activity > 0 && (
            <p className={styles.hint}>
              {view.more_activity} older entr{view.more_activity === 1 ? "y" : "ies"} not shown.
            </p>
          )}
        </>
      ) : (
        <div className={look.empty}>
          <p>Nothing yet with {view.name}.</p>
        </div>
      )}

      {opened && (
        <EntrySheet
          contactId={view.id}
          name={view.name}
          transactionId={opened.id}
          title={opened.title}
          onClose={() => {
            setOpened(null);
          }}
        />
      )}
    </>
  );
}
