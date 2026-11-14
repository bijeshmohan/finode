// The Split of the Add screen (people_editor.html, income_editor.html): who a bill is shared with and how, who paid;
// or which part of an income is theirs and who received some of it for you. Only what is typed for the people ticked
// is sent; the server works out the rest and its preview shows it (SharePreview).
import { type ReactNode, useState } from "react";
import { Link } from "react-router";

import { Icon } from "../../components/Icon";
import { labelOf } from "./kinds";
import { PeopleSheet } from "./PeopleSheet";
import { Picker } from "./Picker";
import type { EntryFormView, PickGroup } from "./queries";
import type { ExpensePerson, ExpenseShareState, IncomePerson, IncomeShareState, Method } from "./share";
import styles from "./ShareEditor.module.css";

const METHODS: [Method, string][] = [
  ["equal", "Equally"],
  ["exact", "Amounts"],
  ["percentage", "%"],
  ["shares", "Shares"],
];

function only(groups: PickGroup[], titles: string[]): PickGroup[] {
  return groups.filter((g) => titles.includes(g.title));
}

interface FieldPickProps {
  label: string;
  empty: string;
  value: string | null;
  groups: PickGroup[];
  clearable?: boolean;
  onChange: (id: string | null) => void;
}

/** A labelled field that opens the picker (pickers.html account_pick / category_pick). */
function FieldPick({ label, empty, value, groups, clearable = false, onChange }: FieldPickProps) {
  const [open, setOpen] = useState(false);
  const shown = labelOf(value, groups);
  return (
    <div className={styles.under}>
      <span aria-hidden="true">{label}</span>
      <button
        type="button"
        className={shown ? styles.fieldPick : `${styles.fieldPick} ${styles.empty}`}
        aria-haspopup="dialog"
        aria-label={`${label}: ${shown ?? empty}`}
        onClick={() => {
          setOpen(true);
        }}
      >
        <span>{shown ?? empty}</span>
      </button>
      {open && (
        <Picker
          open
          title={label}
          groups={groups}
          value={value}
          {...(clearable ? { clearable: empty } : {})}
          onChange={onChange}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}

function NoPeople({ what }: { what: string }) {
  return (
    <div className={styles.empty}>
      <p>Add the people you share {what} with first.</p>
      <Link className={styles.button} to="/people/new">
        Add a person
      </Link>
    </div>
  );
}

interface PeopleListProps<P extends { contactId: string }> {
  people: EntryFormView["people"];
  chosen: P[];
  make: (contactId: string) => P;
  onChange: (people: P[]) => void;
  children: (person: P, name: string, set: (next: Partial<P>) => void) => ReactNode;
  before?: ReactNode;
}

/** The people ticked, one row each with a Remove, and "+ Add people" opening the sheet. */
function PeopleList<P extends { contactId: string }>({
  people,
  chosen,
  make,
  onChange,
  children,
  before,
}: PeopleListProps<P>) {
  const [adding, setAdding] = useState(false);
  const nameOf = (id: string) => people.find((p) => p.id === id)?.name ?? "";
  const toggle = (id: string) => {
    onChange(chosen.some((p) => p.contactId === id) ? chosen.filter((p) => p.contactId !== id) : [...chosen, make(id)]);
  };
  return (
    <div className={styles.tile}>
      {before}
      {chosen.map((person) => {
        const name = nameOf(person.contactId);
        return (
          <div key={person.contactId} className={styles.shareRow}>
            <span className={styles.name}>{name}</span>
            {children(person, name, (next) => {
              onChange(chosen.map((p) => (p.contactId === person.contactId ? { ...p, ...next } : p)));
            })}
            <button
              type="button"
              className={styles.remove}
              aria-label={`Remove ${name}`}
              onClick={() => {
                toggle(person.contactId);
              }}
            >
              <Icon name="close" />
            </button>
          </div>
        );
      })}
      <button
        type="button"
        className={styles.addPeople}
        onClick={() => {
          setAdding(true);
        }}
      >
        + Add people
      </button>
      {adding && (
        <PeopleSheet
          people={people}
          chosen={chosen.map((p) => p.contactId)}
          onToggle={toggle}
          onClose={() => {
            setAdding(false);
          }}
        />
      )}
    </div>
  );
}

/** A disclosure that starts open when it already holds something, then is the person's to open and close. */
function Extra({ title, startOpen, children }: { title: string; startOpen: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <details
      className={styles.extra}
      open={open}
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
      }}
    >
      <summary>
        <span>{title}</span>
        <Icon name="chevron-right" />
      </summary>
      <div className={styles.extraBody}>{children}</div>
    </details>
  );
}

function Value({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <input
      className={styles.value}
      type="text"
      inputMode="decimal"
      autoComplete="off"
      aria-label={label}
      value={value}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  );
}

interface ExpenseProps {
  share: ExpenseShareState;
  people: EntryFormView["people"];
  groups: PickGroup[];
  onChange: (share: ExpenseShareState) => void;
}

export function ExpenseShareEditor({ share, people, groups, onChange }: ExpenseProps) {
  if (people.length === 0) return <NoPeople what="costs" />;
  const set = (next: Partial<ExpenseShareState>) => {
    onChange({ ...share, ...next });
  };
  const valued = share.method !== "equal";
  const nameOf = (id: string) => people.find((p) => p.id === id)?.name ?? "";
  return (
    <div className={styles.editor}>
      <FieldPick
        label="Category"
        empty="Uncategorised"
        clearable
        value={share.categoryId}
        groups={only(groups, ["Expenses"])}
        onChange={(categoryId) => {
          set({ categoryId });
        }}
      />
      <FieldPick
        label="You paid from"
        empty="Choose…"
        value={share.accountId}
        groups={only(groups, ["Assets", "Liabilities"])}
        onChange={(accountId) => {
          set({ accountId });
        }}
      />
      <fieldset className={styles.plain}>
        <legend className={styles.legend}>Split</legend>
        <div className={styles.seg}>
          {METHODS.map(([key, name]) => (
            <label key={key}>
              <input
                type="radio"
                name="split_method"
                checked={share.method === key}
                onChange={() => {
                  set({ method: key });
                }}
              />
              <span>{name}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <PeopleList<ExpensePerson>
        people={people}
        chosen={share.people}
        make={(contactId) => ({ contactId, value: "", paid: "" })}
        onChange={(chosen) => {
          set({ people: chosen });
        }}
        before={
          <div className={styles.shareRow}>
            <span className={styles.name}>You</span>
            {valued && (
              <Value
                label="Your share value"
                value={share.selfValue}
                onChange={(selfValue) => {
                  set({ selfValue });
                }}
              />
            )}
          </div>
        }
      >
        {(person, name, change) =>
          valued && (
            <Value
              label={`${name}'s share value`}
              value={person.value}
              onChange={(value) => {
                change({ value });
              }}
            />
          )
        }
      </PeopleList>
      <Extra title="Someone else paid some of it" startOpen={share.people.some((p) => p.paid !== "")}>
        <label className={styles.paid}>
          <span>
            You paid <span className={styles.muted}>(blank: whatever the others did not)</span>
          </span>
          <input
            className={styles.value}
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={share.selfPaid}
            onChange={(event) => {
              set({ selfPaid: event.target.value });
            }}
          />
        </label>
        {share.people.map((p) => (
          <label key={p.contactId} className={styles.paid}>
            {nameOf(p.contactId)} paid
            <input
              className={styles.value}
              type="text"
              inputMode="decimal"
              autoComplete="off"
              value={p.paid}
              onChange={(event) => {
                set({
                  people: share.people.map((q) =>
                    q.contactId === p.contactId ? { ...q, paid: event.target.value } : q,
                  ),
                });
              }}
            />
          </label>
        ))}
      </Extra>
    </div>
  );
}

interface IncomeProps {
  share: IncomeShareState;
  people: EntryFormView["people"];
  groups: PickGroup[];
  onChange: (share: IncomeShareState) => void;
}

export function IncomeShareEditor({ share, people, groups, onChange }: IncomeProps) {
  if (people.length === 0) return <NoPeople what="money" />;
  const set = (next: Partial<IncomeShareState>) => {
    onChange({ ...share, ...next });
  };
  const nameOf = (id: string) => people.find((p) => p.id === id)?.name ?? "";
  return (
    <div className={styles.editor}>
      <FieldPick
        label="Earned from"
        empty="Uncategorised"
        clearable
        value={share.categoryId}
        groups={only(groups, ["Income"])}
        onChange={(categoryId) => {
          set({ categoryId });
        }}
      />
      <FieldPick
        label="Paid into"
        empty="Choose…"
        value={share.accountId}
        groups={only(groups, ["Assets", "Liabilities"])}
        onChange={(accountId) => {
          set({ accountId });
        }}
      />
      <fieldset className={styles.plain}>
        <legend className={styles.legend}>
          Their part <span className={styles.muted}>(you hold it for them; only the rest is your income)</span>
        </legend>
        <PeopleList<IncomePerson>
          people={people}
          chosen={share.people}
          make={(contactId) => ({ contactId, theirs: "", received: "" })}
          onChange={(chosen) => {
            set({ people: chosen });
          }}
        >
          {(person, name, change) => (
            <Value
              label={`${name}'s part`}
              value={person.theirs}
              onChange={(theirs) => {
                change({ theirs });
              }}
            />
          )}
        </PeopleList>
      </fieldset>
      <Extra title="Someone else received some of it for you" startOpen={share.people.some((p) => p.received !== "")}>
        {share.people.map((p) => (
          <label key={p.contactId} className={styles.paid}>
            {nameOf(p.contactId)} received
            <input
              className={styles.value}
              type="text"
              inputMode="decimal"
              autoComplete="off"
              value={p.received}
              onChange={(event) => {
                set({
                  people: share.people.map((q) =>
                    q.contactId === p.contactId ? { ...q, received: event.target.value } : q,
                  ),
                });
              }}
            />
          </label>
        ))}
      </Extra>
    </div>
  );
}
